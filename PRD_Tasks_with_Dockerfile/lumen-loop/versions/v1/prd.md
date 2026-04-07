# LumenLoop: Launch Sales, Device Lifecycle, and Aftercare API

LumenLoop is the system we use to run a product launch “as one coherent story,” not as a pile of disconnected checkout, warehouse, and support tools.

If you’re integrating with our storefront, our fulfillment line, or our support console, you need the same answers to stay true even after weeks of messy reality. Did we *actually* promise a unit to this customer, or was it only a draft? If a payment falls apart later—dispute, chargeback, an authorization that went stale—what stops, and what cleanup is still allowed? If a quality issue shows up after shipping, how do we contain it without rewriting history? And when we refund, replace, reverse credit, or quarantine inventory, do the numbers still make sense?

## A program is one launch, one world

Everything in LumenLoop lives inside a single `program`.

A program is how we model a launch: one product generation, one region, one inventory pool, one support policy, one quality posture. If two programs both sell a device with the same name, that’s still two separate worlds.

A program has a single monotone counter called **ops runs**. It starts at 0 and increments only when you explicitly run ops. Ops runs are how we get “time-like” behavior without calendar time: holds expiring, warranties aging out, staleness escalating, posture decisions landing at predictable checkpoints.

In practice, ops runs map to the moments we say “we’re closing the operational loop for this cycle” — reconciling open holds, expiring stale things, and computing the program’s posture for what’s allowed next.

## Program posture: how the launch behaves in the real world

A program has one posture at a time. Posture is the launch’s “global stance” and it changes how a lot of actions behave across orders, devices, trade-ins, and returns.

When posture changes, we want it to be obvious to integrators. You should feel it immediately because actions start returning posture-related errors, and the program read endpoint shows the new posture.

In practice there are four postures. **PROGRAM_ACTIVE** is normal selling and fulfillment. **PROGRAM_GUARDED** means we’re still operating, but we stop expanding commitments until operational risk is cleaned up. **PROGRAM_FROZEN** is containment mode: new commitments and most value-extending actions stop, while risk-reducing cleanup keeps going. **PROGRAM_CLOSED** means the launch is over; it’s terminal and read-only.

### What posture blocks (and what it never blocks)

In **PROGRAM_GUARDED**, we block actions that **expand commitments** — anything that increases our promises, increases our risk, or increases the blast radius. That includes creating new paid orders, granting new credits, shipping replacements, and moving a customer from a restricted standing back into full standing. The goal is simple: “clean up first.”

Refreshing payment on an order that is **ON_HOLD** for payment refresh is also blocked in **PROGRAM_GUARDED**. If a client calls `POST /orders/{order_id}/refresh_payment` while guarded, the request fails with `ERR_PROGRAM_REVIEW_REQUIRED` and does not create a new authorization.

In **PROGRAM_FROZEN**, we block **almost everything that creates or extends customer-facing value**, because we’re in containment mode. But we *do not* want freeze to prevent cleanup. Even in frozen posture, the following remain allowed because they reduce risk:

Canceling an order that hasn’t shipped is still allowed, as is voiding an authorization we no longer intend to capture. Returns already in motion can still be received and completed as refunds once eligible. Ops can quarantine inventory and devices, teams can open/acknowledge/resolve alerts, and Ops can still run ops to apply the checkpoint rules that keep the program consistent.

In **PROGRAM_CLOSED**, nothing mutates. Closing a program is deliberately conservative and only happens when there’s nothing left to clean up.

### How posture changes

Some posture changes happen immediately, because they’re emergency containment decisions. Others land at the end of an ops run, because the whole point of ops runs is to keep posture decisions predictable and “batchy” for operators.

A program becomes **PROGRAM_GUARDED** when there’s at least one **OPEN** alert, or when we’re in a supply shortfall state—meaning we’ve committed more units than we can safely ship from non-quarantined stock. We don’t silently cancel people; we stop expanding commitments until operators fix the shortfall.

A program becomes **PROGRAM_FROZEN** immediately when a quality campaign of type **RECALL** is opened for the program.

A program becomes **PROGRAM_FROZEN** at the end of an ops run if three or more payments entered **CHARGEBACK_LOST** during that run, if five or more customers are **LOCKED** at the moment the run closes, or if any alert stayed **OPEN** across two ops runs.

A program can be manually frozen by Ops, but manual freeze is still treated like any other freeze: you can’t just unfreeze without actually being eligible.

### Unfreezing is not a toggle

Unfreezing is only allowed when the program is genuinely stable again. We only allow it when there’s no recall campaign that isn’t **CLOSED**, there are no alerts in **OPEN** status, and the program has completed at least one full ops run since it most recently entered **PROGRAM_FROZEN**.

If those aren’t true, the unfreeze request fails. That “cool-off ops run” requirement exists so teams don’t freeze/unfreeze repeatedly while the underlying mess is still in flight.

### Closing a program

Closing is terminal and is meant for when the launch is truly done. We only allow closing when the posture is **PROGRAM_ACTIVE**, there are no **OPEN** alerts, there are no orders in **SUBMITTED**, **ON_HOLD**, **SHIPPED**, or **DELIVERED**, there are no returns in **REQUESTED**, **APPROVED**, **INBOUND**, or **RECEIVED**, there are no claims in **OPEN**, **APPROVED**, **INBOUND**, **RECEIVED**, or **ADVANCE_SHIPPED**, there are no adjustments still **PENDING**, and there is no quality campaign that isn’t **CLOSED**.

If any of that is still true, the program is not closable. The point of closing is: “there is nothing left that can change, so the history is safe to archive.”

## Customers: standing, credit, and “you owe us” balances

Customers are the center of the launch story. They place orders, ship trade-ins, activate devices, and request returns.

Customers have **standing** that changes based on risk and cleanup. Standing isn’t a moral judgment; it’s simply how we keep the launch stable when reality gets messy.

### Customer statuses
Customers can be **ACTIVE**, **LIMITED**, **LOCKED**, or **CLOSED**. Active is normal behavior. Limited means the customer can still read and clean up their history, but they can’t create new purchase commitments (you’ll see this when they owe money, or when we’re waiting on a device to come back from an aftercare swap). Locked is a stronger restriction used for chargebacks, reversals, and serious mismatches; locked customers can still do certain cleanup actions already in motion, but they can’t place new orders, activate devices, or apply credit. Closed is terminal for the program.

Standing is felt across the system. If a customer becomes locked, it is not “just a flag.” It causes downstream restrictions on orders, payments, and devices that depend on that customer.

### Credit and balance due

Customers have two money-like numbers. **Credit balance** is store credit they can use toward purchases (most commonly from trade-ins). **Balance due** is money they owe us because we had to claw back value after the fact (for example, a trade-in was rejected after provisional credit, or we lost a chargeback).

If a customer has a positive balance due, their standing is **LIMITED** (unless they are **LOCKED** or **CLOSED**).

We intentionally do *not* allow “negative credit.” If a customer owes us more than their current credit balance, the remainder becomes a balance due. Credit balance stays at zero.

Customers can settle a balance due via a settlement action. When a balance due hits zero, they become eligible to return to full standing at the close of the next ops run (assuming nothing else is blocking them).

Becoming eligible is not the same thing as changing standing automatically. Standing changes are explicit: even after a customer is eligible, an operator must call the unlock endpoint to return the customer to **ACTIVE**.

### What creates credit (and what can remove it later)

Trade-ins can create credit. Support can also issue goodwill credit, but in this version of LumenLoop we treat goodwill as a special-case trade-in credit reversal flow (it still becomes credit, and it still can be reversed if it was issued in error).

Trade-in credit has a concept of **provisional** vs **final**, but we don’t make clients micromanage that. What clients see is simple:
credit balance can go up when trade-in credit is issued, it can go down when credit is applied to an order, and it can go down again if previously issued credit is reversed later.

That reversal case is exactly why balance due exists.

### What locks a customer

A customer becomes **LOCKED** when any card payment for that customer enters **CHARGEBACK_LOST**, when a trade-in credit is reversed and that reversal leaves any positive balance due, when an aftercare swap becomes overdue (we shipped an advance replacement but still haven’t received the original device by the deadline), or when a credit adjustment is voided or clawed back and that reversal leaves any positive balance due.

When a customer becomes locked, we immediately stop actions that would extend access or value: no new orders, no device activation, no creating new trade-ins, and no using credit.

We also treat locking as a posture event that creates operational work: it opens an alert.

## Inventory and build lots: the supply we can actually ship

We model inbound manufacturing supply as **build lots**. A build lot is simply “a known chunk of devices built under the same build tag,” which matters because quality campaigns typically target tags.

Lots are not customer-visible. They exist so ops and fulfillment can reason about what’s shippable.

Build lots move through a simple lifecycle. When a lot is **AVAILABLE** it can be used for shipping; when it’s **QUARANTINED** it can’t be used for shipping or replacement; and when it’s **CONSUMED** there are no shippable units left in that lot.

### The headline number: available to commit units

Programs expose one unit-facing number: **available to commit units**.

This is the number storefronts use to decide whether we can accept new paid orders without overpromising. It is intentionally conservative:
it reflects only units that are actually shippable (non-quarantined supply), it already accounts for units committed by existing submitted orders, and it also accounts for the replacement reserve described below.

This number should never “bounce” in surprising ways. When it changes, it’s because supply changed, commitments changed, or a quality decision removed supply from the shippable pool.

### Replacement reserve

At program creation, we set aside **five units** as a replacement reserve. Those units are not offered for sale. They exist so we can replace defective or recalled devices without having to steal inventory from new customers.

Replacement reserve is not exposed as a separate field. You experience it through behavior:
the program’s available-to-commit number will run lower than raw supply by five units, replacement actions can still succeed even when available-to-commit is zero, and once we burn through the reserve, replacement actions start failing (even if we still have sale inventory).

In rare cases, ops may choose to fulfill replacements from sale inventory once the reserve is depleted. When that happens, replacement shipping reduces the available-to-commit number, because we’re now consuming inventory that would otherwise have been sellable.

## Orders: drafts, commitments, holds, and fulfillment

Orders are how customers commit to a unit. A draft is not a commitment. A submitted order is a promise we take seriously — which is why it has downstream consequences and strict reversals.

Each order represents **one device unit** in this program (plus optional add-ons like a care plan). We keep it one unit so that inventory and device lifecycle stay auditable.

Orders start as **DRAFT**. When the customer submits, the order becomes **SUBMITTED** and the program treats it as a real commitment. Sometimes a submitted order can’t safely move forward without a customer action or an operator decision; in those cases it goes **ON_HOLD** until the blocking issue is addressed or ops eventually cleans it up. When fulfillment ships the unit, the order becomes **SHIPPED**, and when delivery is confirmed it becomes **DELIVERED**. If the order is canceled before shipping, it becomes **CANCELED**. If it stays unresolved on hold across the checkpoint rules, ops can drop it as **EXPIRED**. And if the customer completes a return as a refund, the order becomes **REFUNDED**.

### What “submitted” really means

Submitting an order does several things at once in business terms:
we commit one unit out of the program’s sellable capacity, we deduct any customer credit being used right away, and we create a card payment authorization for the remainder (if any).

Submitted orders are the “real” orders. They should never be silently edited into something else. Corrections happen through cancel, hold, expire, return, refund, or replacement.

### Payment authorization and capture

Card payments start as **AUTHORIZED**. We only **CAPTURE** the payment when the order ships.

We do that for a reason: we don’t want to charge people for something that never left the warehouse.

Authorizations are not meant to live forever. If an order is still unshipped when the next ops run closes, we release the authorization and the order goes **ON_HOLD** for payment refresh. The unit remains committed for one more ops run so the customer can refresh payment.

If the order is still on hold for payment refresh when the *next* ops run closes, the order becomes **EXPIRED**. Expiring an order is not “cancel.” It’s a forced cleanup: we release the committed unit and unwind the credit usage, because we’re no longer holding the order open.

### Credit on orders

Orders can be partially paid with customer credit. Credit use is simple from a client’s point of view:
you can’t apply more credit than the customer has, credit comes back if the order cancels or expires before shipping, and credit also comes back on a refund—unless the customer owes us money, in which case the refund reduces balance due first.

That last bit is important. We don’t mint new credit for someone who owes us money.

### What can put an order on hold

Orders go **ON_HOLD** when something happens that makes it unsafe to continue *without a human decision* or a customer action. The most common causes:
stale authorizations that were released at an ops-run checkpoint, a customer becoming locked, a trade-in credit reversal that creates balance due, a supply shortfall (we can’t safely ship committed orders from non-quarantined supply), or a ship-hold campaign that prevents shipping from the lots we’d normally use.

While on hold, orders can still be read, and they can still be canceled (if not shipped), but they don’t move forward automatically. The point of on hold is that you should feel “stop and decide.”

In particular, attempting to ship an order that is **ON_HOLD** fails with `ERR_ORDER_ON_HOLD`.

### Canceling an order

Canceling is a containment action. It is allowed even while the program is guarded or frozen, as long as the order hasn’t shipped.

Canceling does not rewrite history; it unwinds:
the order’s unit commitment returns to available-to-commit, any authorized payment is voided, any applied credit returns (reducing balance due first if the customer owes money), and if a care plan was purchased for the order it is voided.

Canceling is intentionally not allowed once the order is shipped. After shipping, you go through returns.

If you attempt to cancel an order that is already **SHIPPED** or **DELIVERED**, the request fails with `ERR_ORDER_NOT_CANCELABLE`.

## Shipping and devices: serial reality

Shipping is where we leave the world of “units” and enter the world of serialized devices.

When an order ships, we capture the authorized card payment (if any), we create a device record with a serial number and a build tag, and the order becomes **SHIPPED**.

Delivery confirmation moves the order to **DELIVERED**. We treat delivery as a meaningful milestone because a lot of downstream policies depend on it: activation, return windows, and support eligibility.

Devices move through a few practical states: they can exist as a record before shipping (**PROVISIONED**, usually for replacements), they ship (**SHIPPED**), they can be activated by the customer (**ACTIVE**), and they can be quarantined by quality campaigns (**QUARANTINED**). Once a device comes back, it ends up **RETURNED** or **SCRAPPED** depending on inspection and containment decisions.

A device can be quarantined even after shipping. That is the whole point of a recall workflow.

### Activation

Activation is customer-driven and is a big deal. It is the moment we say: “this device is now in the customer’s world.”

Activation is a **customer-only** action. If `X_Actor_Type` is `Support` or `Ops`, `POST /devices/{device_id}/activate` fails with `403 ERR_FORBIDDEN_FOR_ACTOR`.

Activation is allowed only when the order is delivered, the customer is not locked, the device is not quarantined, and the program is not frozen (with the recall-remediation exception described later).

If activation is attempted when the order is not delivered (for example, the order is **SHIPPED** but not **DELIVERED**), the request fails with `ERR_DEVICE_NOT_ACTIVATABLE`.

When a device becomes active, the device status becomes **ACTIVE**, the warranty clock for that device begins (tracked in ops runs), and if the order included a care plan, the care plan becomes active.

Activation is not reversible as a simple “toggle.” If a customer returns a device, that is handled through returns. If a device is quarantined, that is handled through quality campaigns. We do not “de-activate” history.

## Care plans: aftercare that depends on device reality

Care plans are optional add-ons purchased with an order. A care plan exists because customers want predictable coverage, and support needs to know if a customer is covered without reconstructing purchase history.

Care plans have their own lifecycle because “bought a plan” is not the same thing as “a covered device exists and is active.”

Care plans are not transferable between customers. A plan follows the order and the device reality created by that order.

If a device is quarantined under a recall, the plan pauses. The plan does not silently remain active while we’re telling customers “don’t use this device.”

If a refunded return occurs, the plan is canceled. If a replacement occurs through the returns flow, the plan follows the replacement device.

When a plan follows a replacement device, it follows the *device reality*, not just the order record. If the plan was **ACTIVE** but the replacement device isn’t activated yet, the plan goes back to **PENDING_ACTIVATION** until the replacement is activated. If the plan was **PAUSED** due to a recall quarantine, it stays paused until there’s a non-quarantined replacement device and it is activated.

## Aftercare claims: warranty service and recall swaps

Returns are about undoing a purchase. Claims are about keeping the order intact while fixing a device that failed after it became real in the customer’s life.

A claim is tied to a specific device (and that device’s order). A claim never refunds the order and never changes the order’s payment. It exists to do one thing: replace a device under coverage without rewriting history.

We intentionally don’t let workflows fight each other. A device can have at most one non-terminal claim at a time, and an order can’t have a non-terminal return and a non-terminal claim at the same time.

Claims can also be canceled while they’re still early-stage — before we’ve shipped any replacement device.

### Claim types (what coverage you’re using)

Claims come in three types. **WARRANTY** is standard program warranty: warranty starts when a device is activated and lasts twelve ops runs (for example, if you activate at ops run 3, the device stays in warranty through ops run 14 and the warranty is expired once ops run 15 closes). **CARE_PLAN** means the replacement is covered by an active care plan for that order. **RECALL** is for devices quarantined by a recall campaign, and it exists to get those devices out of the field quickly.

### The normal path: receive first, then replace

For **WARRANTY** and **CARE_PLAN** claims, we don’t ship a replacement until the original device is received and inspected. That keeps inventory honest and avoids sending out two devices for one order unless we have a reason.

Claim replacements are still “replacement actions” in inventory terms. They draw from the replacement reserve first, and they follow the same behavior you see elsewhere: a replacement can succeed even when available-to-commit is zero (until reserve is depleted), and once reserve is gone we either fail or deliberately consume sale inventory (which reduces available-to-commit).

### The recall exception: advance replacement with a deposit hold

For **RECALL** claims, Support can choose an **advance replacement**. We ship the replacement device first, and we wait for the quarantined device to come back.

Advance replacement is riskier, so it has real downstream effects you can observe. We place a **$150 deposit** into the customer’s **balance due**, the customer becomes **LIMITED** until that deposit is released, and any unshipped order for that customer becomes **ON_HOLD**.

Once the old device is received and the claim is completed, we release the deposit. Releasing a deposit follows the same rule as refunds: it reduces balance due first; if there is no balance due, it becomes credit.

Claims also aren’t meant to sit forever. If a claim is approved but the device still isn’t marked inbound when the next ops run closes, it expires. If a claim is inbound but still isn’t received when the next ops run closes after that, it expires. (Advance replacements don’t expire; they escalate overdue instead.)

If the old device still hasn’t been received by the time the **second** ops run after the advance replacement ships closes, we treat it as overdue: the customer becomes **LOCKED** and we open an alert. The deposit is still released if the device eventually comes back, but we don’t silently “make it all go away” — the overdue alert must be resolved and the customer must be explicitly unlocked.

### Replacement device reality

Claim replacements create a new device record tied to the original order. The order stays delivered, but its “current device” becomes the replacement.

Care plans follow the replacement device (as described above). Warranty follows the device, not the order: the replacement device starts its own warranty clock when it is activated.

Activation is normally blocked while the program is frozen. But if the program is frozen because of a recall campaign, activating the replacement device shipped as part of that recall claim is allowed — it’s remediation. (The quarantined original device is still not activatable.)

## Trade-ins: credit that can be adjusted later

Trade-ins are how we let customers trade in an old device for credit toward a new one. The operational reality is that trade-ins aren’t always clean:
sometimes the device arrives late, sometimes it’s not what was described, and sometimes the quoted value needs adjustment after inspection.

That’s why trade-ins have lifecycle and why trade-in credit can be adjusted or reversed.

Trade-ins start as **DRAFT** and become **SUBMITTED** when the customer commits. Once the device is on the way, the trade-in is **INBOUND**. Appraisal is the moment we finalize the outcome (**APPRAISED**) and, when applicable, issue final credit (**CREDITED**). If the trade-in sits stale long enough, ops can drop it as **EXPIRED**. And if we later need to correct previously issued credit, the trade-in can move to **REVERSED** as a compensating action.

### Provisional credit: when we trust, and when we don’t

We sometimes issue credit before appraisal, because customers want to use credit immediately. But we only do that when it’s safe.

A submitted trade-in receives provisional credit immediately only when the program is **PROGRAM_ACTIVE**, the customer is **ACTIVE**, the customer has zero balance due, the quoted trade-in credit is **$300 or less**, and there is no open alert tied to that customer.

When provisional credit is issued, it increases the customer’s credit balance immediately.

If a trade-in does not qualify for provisional credit, it can still be submitted — it just won’t change credit balance until appraisal.

### Appraisal: the moment truth lands

Appraisal finalizes the trade-in.
If the trade-in is accepted, we finalize a value. If provisional credit was already issued and the final value is lower, the difference becomes balance due; if the final value is higher, the extra becomes additional credit. If the trade-in is rejected, the final value is zero—any previously issued provisional credit becomes balance due, and the customer is locked.

On rejection, “becomes balance due” is literal: the customer’s credit balance is reduced (never below zero) and the provisional amount is recorded as balance due.

That “difference becomes balance due” behavior is why credit is not simply a permanent gift. It’s a value transfer that can be corrected after inspection.

### Reversing trade-in credit later

Even after credit has been issued, there are rare cases where we need to reverse it: fraud, serial mismatch, or a policy violation discovered later.

Reversal is not “editing the credit number.” It’s a compensating action:
we remove as much as we can from the customer’s current credit balance, and if the customer no longer has enough credit to cover the reversal, the remainder becomes balance due. If the reversal creates any balance due, the customer becomes locked and an alert is opened.

When a trade-in reversal happens, we also take a conservative posture on open orders:
any unshipped order for that customer becomes **ON_HOLD**, and shipping is blocked until the customer’s balance due is settled and the alert is resolved.

This is the system preferring containment over convenience.

## Adjustments: when humans fix the ledger

Most of the time, credit and balance due change because of real-world workflows: trade-ins, refunds, chargebacks, and settlements. But sometimes Support or Ops needs to correct the numbers without pretending the history didn’t happen.

Adjustments are small, auditable actions that move customer balances. They are deliberately not “edit the customer record.” They have their own lifecycle and they can be unwound — but only briefly.

Adjustments start out pending and then get applied. If an applied adjustment was a mistake, you void it (within the ops-run window described below).

We support three adjustment types: **GOODWILL_CREDIT** (add store credit), **WRITE_OFF** (reduce balance due because we decide not to collect it), and **CREDIT_CLAWBACK** (remove credit that shouldn’t have been there).

Goodwill credit is value-extending, so it follows strict gates: it’s only allowed when the program is active and not guarded, the customer is **ACTIVE**, the customer has no balance due, and there are no open alerts tied to that customer.

Write-offs are cleanup. They’re allowed even while the program is frozen.

Clawbacks behave like trade-in reversals: we remove as much as we can from credit balance, and if there isn’t enough, the remainder becomes balance due. If a clawback creates any balance due, the customer becomes locked and an alert is opened, and any unshipped order for that customer goes on hold.

### Adjustments can be voided, but only until the next ops run closes

We allow operators to undo an applied adjustment if they made a mistake — but we don’t want the ledger to feel mutable forever. Once you close the next ops run after an adjustment is applied, it’s considered final and it can’t be voided.

Voiding a credit-adding adjustment behaves like any other credit reversal: if the customer already spent some of that credit, the missing portion becomes balance due (credit never goes negative). That can lock the customer and open an alert.

## Returns and replacements: corrections without rewriting history

Once something has shipped, corrections happen through returns, refunds, replacements, and aftercare claims.

Returns exist because we don’t want “refund an order” to be a random action on an order record. Returns are the real-world workflow: request → approve → receive → resolve.

Returns follow a real workflow. A return starts **REQUESTED**, Support can move it to **APPROVED**, it can be marked **INBOUND** while it’s in transit, and once the warehouse receives it and records inspection it becomes **RECEIVED**. From there it’s resolved as **COMPLETED** (refund or replacement), or it can be denied as **REJECTED**.

### Return eligibility depends on device reality

We don’t allow “return anything anytime” because it creates obvious abuse vectors and it makes inventory math meaningless.

A standard “no longer wanted” return is only eligible when:
the order is delivered, the device has not been activated, the customer is not locked, and the program is not closed.

Defect and recall returns are different. If a device is quarantined under a recall, the customer can return it even if it was activated. That is part of containment.

If a device was activated and it is *not* quarantined under a recall, returns aren’t how we do aftercare. That’s what claims are for: warranty and care-plan replacements without refunding the order.

We also don’t allow multiple overlapping returns on the same order. One order can have at most one non-terminal return at a time.

### Inspection outcome: whether inventory comes back

When a return is received, warehouse records an inspection outcome:

If the device was never activated and it isn’t quarantined, the warehouse can mark it **RESTOCK**. If it’s usable but belongs in refurb channels (not back into this program’s sellable pool), it’s **REFURB**. If it’s not usable, it’s **SCRAP**.

If an inspection outcome is invalid for the device’s reality (for example, `RESTOCK` for an activated device or a quarantined device), the request fails with `ERR_INVALID_REQUEST` and makes no changes.

RESTOCK is the only outcome that increases the program’s available-to-commit units. REFURB and SCRAP do not.

### Completing a return: refund vs replacement

A return is completed in one of two ways:
as a **Refund** (we refund the order, unwind the payment, and cancel the care plan) or as a **Replacement** (we ship a replacement device and keep the financial side intact).

Replacement is only allowed when the return is received, the inspection outcome is not RESTOCK (replacement is for defect/recall reality, not buyer’s remorse), the program isn’t frozen for reasons other than the recall that caused the replacement, the customer isn’t locked, and replacement stock is available (ideally from reserve).

If replacement cannot be done, support can still complete as refund.

Refund completion sets the order to **REFUNDED**, refunds any captured card payment, returns applied credit to the customer’s credit balance (reducing balance due first), sets the device to **RETURNED** or **SCRAPPED** depending on inspection, and cancels the care plan if it was active (or voids it if it never became active).

Replacement completion creates a new device record tied to the original order, marks the original device as **RETURNED** or **SCRAPPED**, keeps the order delivered while switching its “current device” to the replacement, and carries the care plan forward to the replacement device.

Replacement completion consumes from replacement reserve when possible. When reserve is depleted, replacements consume from sale inventory, which reduces the available-to-commit number.

## Quality campaigns: ship holds and recalls

Quality campaigns are how ops declares “this is a known quality scope” and ensures the system behaves conservatively.

Campaigns are scoped by a build tag prefix. That lines up with how manufacturing and firmware versions cluster, and it lets campaigns affect lots and shipped devices consistently.

In this version there are two campaign types. **SHIP_HOLD** stops shipping from affected lots without automatically quarantining devices already shipped. **RECALL** quarantines affected devices in the field and stops shipping affected lots.

Campaigns start **OPEN**, can move to **CONTAINED** once immediate containment actions have been taken, can be marked **RESOLVED** once remediation is complete, and are ultimately **CLOSED**.

### What a ship-hold does

When a ship-hold campaign is opened:
matching build lots become quarantined, shipping from those lots is blocked, and orders already shipped are not automatically quarantined (this isn’t a recall yet).

When a **SHIP_HOLD** campaign is closed, any build lots that are still `QUARANTINED` solely due to that ship-hold are released back to `build_lot_status=AVAILABLE`, restoring their units to the program’s shippable pool.

### Escalating to a recall

Escalation to recall is explicit. When a campaign is escalated to **RECALL**:
all devices with matching build tags become **QUARANTINED**, activation is blocked for those devices, care plans for those devices become **PAUSED**, and the program posture becomes **PROGRAM_FROZEN** immediately.

Recall is the “stop the world” safety move. We’d rather temporarily over-block than let risky devices continue to be activated.

### Remediation and closing a campaign

A recall campaign cannot be closed until it is actually cleaned up. For our purposes, a quarantined device is considered remediated only when:
it is returned through the return flow and resolved (refund or replacement), or Ops explicitly records a remediation action on the device (a field fix or verified safe state) that moves it out of quarantined status.

When Ops remediates a device, it clears `device_status=QUARANTINED` and restores the device to its pre-quarantine status:
if the device was previously **ACTIVE**, it becomes **ACTIVE** again; if it was never activated (still **SHIPPED**), it remains **SHIPPED**.

If a care plan was **PAUSED** solely due to recall quarantine, it resumes once the device is no longer quarantined (for a previously-active device, the plan becomes **ACTIVE** again).

Once all affected devices are remediated and all affected lots are either consumed, quarantined, or explicitly released, the campaign can be marked resolved, and then closed.

If an operator attempts to `resolve` or `close` a campaign when its prerequisites are not met, the request fails with `ERR_INVALID_REQUEST` and makes no changes.

Closing a campaign is also one of the things that can make a program eligible to unfreeze — but unfreezing still requires no open alerts and a full ops run since the freeze.

Closing a quality campaign does not automatically resolve any associated alerts (including `RECALL_ACTIVE`). Alerts must be explicitly resolved through the alerts API once their underlying situation is clean.

## Alerts: the operational queue that makes risk visible

Alerts are how the system leaves a paper trail for “this got messy.”

Alerts open automatically when a customer becomes locked (`alert_type=CUSTOMER_LOCKED`), when a trade-in credit is reversed, when a payment enters dispute or chargeback lost, when a supply shortfall is detected, when a recall is opened (program-level alert), or when an aftercare swap becomes overdue (advance replacement shipped, but the original device still isn’t received by the deadline).

When a payment is in dispute, resolving the dispute updates only the payment’s `payment_status`:
- `POST /payments/{payment_id}/resolve_dispute` is only valid when `payment_status=DISPUTED`. Otherwise it fails with `ERR_INVALID_STATE_TRANSITION`.
- Resolving a dispute with outcome `REFUNDED` does **not** change the order’s `order_status`. Order refunds are represented only by the returns workflow.
- Resolving a dispute does **not** automatically resolve the `PAYMENT_DISPUTED` alert; alerts remain `OPEN`/`ACKNOWLEDGED` until explicitly resolved.

A payment can be disputed only when it is currently `payment_status=AUTHORIZED` or `payment_status=CAPTURED`. If a payment is `VOIDED`, `REFUNDED`, `CHARGEBACK_LOST`, or otherwise not in a disputable state, `POST /payments/{payment_id}/dispute` fails with `ERR_PAYMENT_NOT_DISPUTABLE` and no `PAYMENT_DISPUTED` alert is created.

Alerts are intentionally deduplicated. If the same underlying situation keeps happening, we keep one open alert per “thing being handled” rather than spamming duplicates.

Alerts move from **OPEN** to **ACKNOWLEDGED** to **RESOLVED**.

Acknowledging means “a human saw it.” It doesn’t resolve the alert or imply the underlying situation is clean.

Resolving requires the underlying situation to actually be clean. For example:
you can’t resolve a chargeback-lost alert while the customer still has balance due, you can’t resolve a trade-in reversal alert while the trade-in is still reversed and the customer is locked, you can’t resolve a supply shortfall alert while the program still can’t cover commitments from shippable supply, you can’t resolve a recall alert until the campaign is closed, and you can’t resolve an aftercare overdue alert until the claim is completed (the device is received and the deposit hold is released).

While any alert is **OPEN**, the program posture is **PROGRAM_GUARDED**, which blocks expansion actions across the system even if the program is otherwise stable.

Alerts are the operational queue for messy reality. When an alert is open, the program shifts into a posture that forces cleanup before we keep expanding commitments.

## Running ops: where cleanup and checkpoint decisions land

Running ops increments the program’s ops run index and applies the checkpoint behavior described throughout this doc.

`POST /programs/{program_id}/run_ops` is serialized per program. If multiple `run_ops` requests arrive concurrently, they are queued rather than rejected; each successful request increments `ops_run_index` by exactly 1 and applies checkpoint rules exactly once.

Running ops is never a “no-op.” It’s the moment we apply:
payment authorization staleness rules (authorize → void + hold), expiration rules for unresolved holds (hold → expire), warranty aging (warranty expires after twelve ops runs from activation), claim staleness and aftercare escalation (approved/inbound claims expiring; advance replacements becoming overdue), adjustment finalization (void windows closing after the next ops run), posture escalation rules (stale alerts, chargeback thresholds, locked-customer thresholds), and inventory posture changes due to quarantines and supply shortfall detection.

If you call run ops, you are asking the system to advance the program’s operational reality.

## When multiple things are wrong: what error you see first

LumenLoop returns errors in a consistent shape: `{ "error": { "code": "ERR_SOMETHING", "message": "..." } }`.

When multiple things are wrong, we try to return the error that best tells the client what to do next.

A few precedence rules matter:
Missing or malformed required context headers always win first. If a session header is required and provided but it doesn’t identify an active session for that actor, you see the session error (that’s different than forgetting the header). “You are not allowed to do this at all” wins before posture—if Support can’t do a customer-only action, you should hear that, not “program is frozen.” For lifecycle transitions (submit, ship, cancel, activate, appraise, reverse, approve, complete, apply, void), an invalid transition wins before posture; fix the action for the current status first. After that, frozen beats guarded. Customer lock beats most other eligibility rules for value-extending actions. And for value-extending actions, if the program is active but guarded due to open alerts, you’ll see review-required before more specific business-rule errors like stock limits or credit thresholds.

For device activation, device quarantine (`ERR_DEVICE_QUARANTINED`) takes precedence over posture errors.

## Idempotency

All mutating endpoints accept an optional idempotency key header. If you repeat the same request with the same key (same path and same payload), you get the same response. If you reuse a key with a different payload, you get an idempotency conflict.

Idempotency keys are scoped to a program. Using the same key value in two different programs is allowed.

---

# Minimal API Surface Appendix

This appendix consolidates the public contract surface: endpoints, required headers, enums, error codes, and the small set of observable fields.

## Required headers

All requests:
- `X_Actor_Id`: opaque string id of the caller
- `X_Actor_Type`: one of `Customer`, `Support`, `Ops`, `System`

Mutating requests made by `Customer`, `Support`, or `Ops` additionally require:
- `X_Session_Id`: opaque string id of an `ACTIVE` session for that actor  
  - Exception: `POST /programs` and `POST /programs/{program_id}/sessions` do not require an existing session.

All mutating requests may include:
- `Idempotency_Key`: opaque string

## Enums

Program:
- `program_posture`: `PROGRAM_ACTIVE` | `PROGRAM_GUARDED` | `PROGRAM_FROZEN` | `PROGRAM_CLOSED`

Customer:
- `customer_status`: `ACTIVE` | `LIMITED` | `LOCKED` | `CLOSED`

Session:
- `session_status`: `ACTIVE` | `ENDED` | `REVOKED`

Build lots:
- `build_lot_status`: `AVAILABLE` | `QUARANTINED` | `CONSUMED`

Orders:
- `order_status`: `DRAFT` | `SUBMITTED` | `ON_HOLD` | `SHIPPED` | `DELIVERED` | `CANCELED` | `EXPIRED` | `REFUNDED`

Payments:
- `payment_status`: `AUTHORIZED` | `CAPTURED` | `VOIDED` | `REFUNDED` | `DISPUTED` | `CHARGEBACK_LOST`

Devices:
- `device_status`: `PROVISIONED` | `SHIPPED` | `ACTIVE` | `QUARANTINED` | `RETURNED` | `SCRAPPED`

Care plans:
- `care_plan_status`: `PENDING_ACTIVATION` | `ACTIVE` | `PAUSED` | `CANCELED` | `VOIDED`

Trade-ins:
- `tradein_status`: `DRAFT` | `SUBMITTED` | `INBOUND` | `APPRAISED` | `CREDITED` | `REVERSED` | `EXPIRED`

Returns:
- `return_status`: `REQUESTED` | `APPROVED` | `INBOUND` | `RECEIVED` | `COMPLETED` | `REJECTED`
- `return_resolution_preference`: `REFUND` | `REPLACEMENT`
- `return_inspection_outcome`: `RESTOCK` | `REFURB` | `SCRAP`

Claims:
- `claim_status`: `OPEN` | `APPROVED` | `INBOUND` | `RECEIVED` | `ADVANCE_SHIPPED` | `COMPLETED` | `CANCELED` | `EXPIRED`
- `claim_type`: `WARRANTY` | `CARE_PLAN` | `RECALL`
- `claim_resolution`: `REPLACEMENT` | `ADVANCE_REPLACEMENT`

Adjustments:
- `adjustment_status`: `PENDING` | `APPLIED` | `VOIDED`
- `adjustment_type`: `GOODWILL_CREDIT` | `WRITE_OFF` | `CREDIT_CLAWBACK`

Quality campaigns:
- `quality_campaign_type`: `SHIP_HOLD` | `RECALL`
- `quality_campaign_status`: `OPEN` | `CONTAINED` | `RESOLVED` | `CLOSED`

Alerts:
- `alert_status`: `OPEN` | `ACKNOWLEDGED` | `RESOLVED`
- `alert_type`: `CUSTOMER_LOCKED` | `PAYMENT_DISPUTED` | `CHARGEBACK_LOST` | `TRADEIN_REVERSAL` | `SUPPLY_SHORTFALL` | `RECALL_ACTIVE` | `AFTERCARE_OVERDUE`

## Error codes

- `ERR_NOT_FOUND`
- `ERR_INVALID_REQUEST`
- `ERR_INVALID_STATE_TRANSITION`

- `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`
- `ERR_SESSION_NOT_ACTIVE`
- `ERR_FORBIDDEN_FOR_ACTOR`

- `ERR_PROGRAM_FROZEN`
- `ERR_PROGRAM_CLOSED`
- `ERR_PROGRAM_REVIEW_REQUIRED`
- `ERR_PROGRAM_NOT_ELIGIBLE_TO_UNFREEZE`
- `ERR_PROGRAM_NOT_ELIGIBLE_TO_CLOSE`

- `ERR_CUSTOMER_LOCKED`
- `ERR_CUSTOMER_CLOSED`
- `ERR_CUSTOMER_NOT_ELIGIBLE`

- `ERR_OUT_OF_STOCK`
- `ERR_BUILD_LOT_QUARANTINED`

- `ERR_ORDER_ON_HOLD`
- `ERR_ORDER_PAYMENT_REQUIRED`
- `ERR_ORDER_NOT_CANCELABLE`

- `ERR_PAYMENT_NOT_REFUNDABLE`
- `ERR_PAYMENT_NOT_DISPUTABLE`

- `ERR_DEVICE_NOT_ACTIVATABLE`
- `ERR_DEVICE_QUARANTINED`

- `ERR_CARE_PLAN_NOT_ELIGIBLE`

- `ERR_TRADEIN_NOT_ELIGIBLE`
- `ERR_TRADEIN_REQUIRES_APPRAISAL`

- `ERR_RETURN_NOT_ELIGIBLE`
- `ERR_RETURN_NOT_RESOLVABLE`

- `ERR_ALERT_NOT_RESOLVABLE`

- `ERR_CLAIM_NOT_ELIGIBLE`
- `ERR_CLAIM_NOT_RESOLVABLE`

- `ERR_ADJUSTMENT_NOT_ELIGIBLE`
- `ERR_ADJUSTMENT_NOT_VOIDABLE`

- `ERR_IDEMPOTENCY_CONFLICT`

## HTTP status codes

LumenLoop uses a small, consistent set of HTTP status codes:

- `200`: successful reads and successful actions that return a resource representation
- `201`: successful creates
- `400`: request is invalid for the contract or current state (most `ERR_*` responses)
- `403`: `ERR_FORBIDDEN_FOR_ACTOR`
- `404`: `ERR_NOT_FOUND`

## Observable fields (responses)

Program:
- `program_id`, `display_name`, `program_posture`, `ops_run_index`, `available_to_commit_units`

Customer:
- `customer_id`, `display_name`, `customer_status`, `credit_balance_cents`, `balance_due_cents`

Session:
- `session_id`, `actor_id`, `actor_type`, `session_status`

Build lot:
- `build_lot_id`, `build_tag`, `build_lot_status`

Order:
- `order_id`, `customer_id`, `order_status`, `model_code`, `unit_price_cents`, `care_plan_price_cents`, `paid_by_credit_cents`, `paid_by_card_cents`, `payment_id`, `device_id`, `care_plan_id`, `tradein_id`

Payment:
- `payment_id`, `order_id`, `payment_status`, `amount_cents`

Device:
- `device_id`, `order_id`, `customer_id`, `serial_number`, `build_tag`, `device_status`

Care plan:
- `care_plan_id`, `order_id`, `customer_id`, `device_id`, `care_plan_status`

Trade-in:
- `tradein_id`, `customer_id`, `tradein_status`, `quoted_credit_cents`, `final_credit_cents`

Return:
- `return_id`, `order_id`, `device_id`, `customer_id`, `return_status`, `resolution_preference`, `inspection_outcome`, `refunded_to_card_cents`, `refunded_to_credit_cents`, `replacement_device_id`

Claim:
- `claim_id`, `order_id`, `device_id`, `customer_id`, `claim_status`, `claim_type`, `claim_resolution`, `inspection_outcome`, `replacement_device_id`

Adjustment:
- `adjustment_id`, `customer_id`, `adjustment_type`, `adjustment_status`, `amount_cents`

Quality campaign:
- `quality_campaign_id`, `campaign_type`, `campaign_status`, `build_tag_prefix`

Alert:
- `alert_id`, `alert_type`, `alert_status`, `opened_ops_run_index`, `customer_id`, `order_id`, `device_id`, `payment_id`, `tradein_id`, `quality_campaign_id`, `claim_id`

## Endpoints

All endpoints are scoped under a program, except `POST /programs` which creates a program.

### Programs

`POST /programs`  
Body: `{ "display_name": "LumenPhone Gen1 US Launch", "unit_price_cents": 79900, "care_plan_price_cents": 9900 }`  
Response: `{ "program_id": "...", "display_name": "...", "program_posture": "PROGRAM_ACTIVE", "ops_run_index": 0, "available_to_commit_units": 0 }`

`GET /programs/{program_id}`  
Response: `{ "program_id": "...", "display_name": "...", "program_posture": "...", "ops_run_index": 0, "available_to_commit_units": 0 }`

`POST /programs/{program_id}/run_ops`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}`.

`POST /programs/{program_id}/freeze`  
Body: `{ "reason": "..." }`  
Response: same shape as `GET /programs/{program_id}`.

`POST /programs/{program_id}/unfreeze`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}`.

`POST /programs/{program_id}/close`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}`.

### Sessions

`POST /programs/{program_id}/sessions`  
Body: `{ "actor_id": "...", "actor_type": "Customer" }`  
Response: `{ "session_id": "...", "actor_id": "...", "actor_type": "...", "session_status": "ACTIVE" }`

`GET /programs/{program_id}/sessions/{session_id}`  
Response: `{ "session_id": "...", "actor_id": "...", "actor_type": "...", "session_status": "..." }`

`POST /programs/{program_id}/sessions/{session_id}/end`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/sessions/{session_id}`.

### Customers

`POST /programs/{program_id}/customers`  
Body: `{ "display_name": "Ava Chen" }`  
Response: `{ "customer_id": "...", "display_name": "...", "customer_status": "ACTIVE", "credit_balance_cents": 0, "balance_due_cents": 0 }`

`GET /programs/{program_id}/customers/{customer_id}`  
Response: `{ "customer_id": "...", "display_name": "...", "customer_status": "...", "credit_balance_cents": 0, "balance_due_cents": 0 }`

`POST /programs/{program_id}/customers/{customer_id}/lock`  
Body: `{ "reason": "..." }`  
Response: same shape as `GET /programs/{program_id}/customers/{customer_id}`.

`POST /programs/{program_id}/customers/{customer_id}/unlock`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/customers/{customer_id}`.

`POST /programs/{program_id}/customers/{customer_id}/settle_balance_due`  
Body: `{ "amount_cents": 1000 }`  
Response: same shape as `GET /programs/{program_id}/customers/{customer_id}`.

### Adjustments

`POST /programs/{program_id}/customers/{customer_id}/adjustments`  
Body: `{ "adjustment_type": "GOODWILL_CREDIT" | "WRITE_OFF" | "CREDIT_CLAWBACK", "amount_cents": 1000 }`  
Response: `{ "adjustment_id": "...", "customer_id": "...", "adjustment_type": "...", "adjustment_status": "PENDING", "amount_cents": 1000 }`

`GET /programs/{program_id}/adjustments/{adjustment_id}`  
Response: same shape as adjustment creation response.

`POST /programs/{program_id}/adjustments/{adjustment_id}/apply`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/adjustments/{adjustment_id}`.

`POST /programs/{program_id}/adjustments/{adjustment_id}/void`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/adjustments/{adjustment_id}`.

### Build lots (Ops only)

`POST /programs/{program_id}/build_lots`  
Body: `{ "build_tag": "A17B", "units": 50 }`  
Response: `{ "build_lot_id": "...", "build_tag": "...", "build_lot_status": "AVAILABLE" }`

`GET /programs/{program_id}/build_lots/{build_lot_id}`  
Response: `{ "build_lot_id": "...", "build_tag": "...", "build_lot_status": "..." }`

### Orders

`POST /programs/{program_id}/customers/{customer_id}/orders`  
Body: `{ "model_code": "LUMENPHONE_G1", "use_credit_cents": 0, "tradein_id": null }`  
Response: `{ "order_id": "...", "customer_id": "...", "order_status": "DRAFT", "model_code": "...", "unit_price_cents": 79900, "care_plan_price_cents": 9900, "paid_by_credit_cents": 0, "paid_by_card_cents": 0, "payment_id": null, "device_id": null, "care_plan_id": null, "tradein_id": null }`

`GET /programs/{program_id}/orders/{order_id}`  
Response: same shape as order creation response.

`GET /programs/{program_id}/orders?customer_id=...&order_status=...`  
Response: `{ "orders": [ { "order_id": "...", "customer_id": "...", "order_status": "...", "model_code": "...", "unit_price_cents": 0, "care_plan_price_cents": 0, "paid_by_credit_cents": 0, "paid_by_card_cents": 0, "payment_id": null, "device_id": null, "care_plan_id": null, "tradein_id": null } ] }`

`POST /programs/{program_id}/orders/{order_id}/submit`  
Body: `{ "include_care_plan": true }`  
Response: same shape as `GET /programs/{program_id}/orders/{order_id}`.

`POST /programs/{program_id}/orders/{order_id}/refresh_payment`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/orders/{order_id}`.

`POST /programs/{program_id}/orders/{order_id}/cancel`  
Body: `{ "reason": "..." }`  
Response: same shape as `GET /programs/{program_id}/orders/{order_id}`.

`POST /programs/{program_id}/orders/{order_id}/ship`  
Body: `{ "build_lot_id": "...", "serial_number": "SN123", "build_tag": "A17B" }`  
Response: same shape as `GET /programs/{program_id}/orders/{order_id}`.

`POST /programs/{program_id}/orders/{order_id}/mark_delivered`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/orders/{order_id}`.

### Payments

`GET /programs/{program_id}/payments/{payment_id}`  
Response: `{ "payment_id": "...", "order_id": "...", "payment_status": "...", "amount_cents": 0 }`

`POST /programs/{program_id}/payments/{payment_id}/dispute`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/payments/{payment_id}`.

`POST /programs/{program_id}/payments/{payment_id}/resolve_dispute`  
Body: `{ "outcome": "CHARGEBACK_LOST" | "REFUNDED" }`  
Response: same shape as `GET /programs/{program_id}/payments/{payment_id}`.

### Devices

`GET /programs/{program_id}/devices/{device_id}`  
Response: `{ "device_id": "...", "order_id": "...", "customer_id": "...", "serial_number": "...", "build_tag": "...", "device_status": "..." }`

`POST /programs/{program_id}/devices/{device_id}/activate`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/devices/{device_id}`.

`POST /programs/{program_id}/devices/{device_id}/remediate`  
Body: `{ "note": "..." }`  
Response: same shape as `GET /programs/{program_id}/devices/{device_id}`.

### Claims

`POST /programs/{program_id}/devices/{device_id}/claims`  
Body: `{ "claim_type": "WARRANTY" | "CARE_PLAN" | "RECALL" }`  
Response: `{ "claim_id": "...", "order_id": "...", "device_id": "...", "customer_id": "...", "claim_status": "OPEN", "claim_type": "...", "claim_resolution": null, "inspection_outcome": null, "replacement_device_id": null }`

`GET /programs/{program_id}/claims/{claim_id}`  
Response: same shape as claim creation response.

`POST /programs/{program_id}/claims/{claim_id}/approve`  
Body: `{ "resolution": "REPLACEMENT" | "ADVANCE_REPLACEMENT" }`  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

`POST /programs/{program_id}/claims/{claim_id}/cancel`  
Body: `{ "reason": "..." }`  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

`POST /programs/{program_id}/claims/{claim_id}/mark_inbound`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

`POST /programs/{program_id}/claims/{claim_id}/receive`  
Body: `{ "inspection_outcome": "REFURB" | "SCRAP" }`  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

`POST /programs/{program_id}/claims/{claim_id}/ship_advance_replacement`  
Body: `{ "replacement_build_lot_id": "...", "replacement_serial_number": "SN999", "replacement_build_tag": "A17B" }`  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

`POST /programs/{program_id}/claims/{claim_id}/complete`  
Body: `{ "replacement_build_lot_id": null|"...", "replacement_serial_number": null|"SN999", "replacement_build_tag": null|"A17B" }`  
Response: same shape as `GET /programs/{program_id}/claims/{claim_id}`.

### Care plans

`GET /programs/{program_id}/care_plans/{care_plan_id}`  
Response: `{ "care_plan_id": "...", "order_id": "...", "customer_id": "...", "device_id": null|"...", "care_plan_status": "..." }`

### Trade-ins

`POST /programs/{program_id}/customers/{customer_id}/tradeins`  
Body: `{ "quoted_credit_cents": 25000 }`  
Response: `{ "tradein_id": "...", "customer_id": "...", "tradein_status": "DRAFT", "quoted_credit_cents": 25000, "final_credit_cents": null }`

`GET /programs/{program_id}/tradeins/{tradein_id}`  
Response: `{ "tradein_id": "...", "customer_id": "...", "tradein_status": "...", "quoted_credit_cents": 0, "final_credit_cents": null|0 }`

`POST /programs/{program_id}/tradeins/{tradein_id}/submit`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/tradeins/{tradein_id}`.

`POST /programs/{program_id}/tradeins/{tradein_id}/mark_inbound`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/tradeins/{tradein_id}`.

`POST /programs/{program_id}/tradeins/{tradein_id}/appraise`  
Body: `{ "accepted": true|false, "final_credit_cents": 20000 }`  
Response: same shape as `GET /programs/{program_id}/tradeins/{tradein_id}`.

`POST /programs/{program_id}/tradeins/{tradein_id}/reverse_credit`  
Body: `{ "reason": "..." }`  
Response: same shape as `GET /programs/{program_id}/tradeins/{tradein_id}`.

### Returns

`POST /programs/{program_id}/orders/{order_id}/returns`  
Body: `{ "resolution_preference": "REFUND" | "REPLACEMENT" }`  
Response: `{ "return_id": "...", "order_id": "...", "device_id": "...", "customer_id": "...", "return_status": "REQUESTED", "resolution_preference": "...", "inspection_outcome": null, "refunded_to_card_cents": 0, "refunded_to_credit_cents": 0, "replacement_device_id": null }`

`GET /programs/{program_id}/returns/{return_id}`  
Response: same shape as return creation response.

`POST /programs/{program_id}/returns/{return_id}/approve`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/returns/{return_id}`.

`POST /programs/{program_id}/returns/{return_id}/mark_inbound`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/returns/{return_id}`.

`POST /programs/{program_id}/returns/{return_id}/receive`  
Body: `{ "inspection_outcome": "RESTOCK" | "REFURB" | "SCRAP" }`  
Response: same shape as `GET /programs/{program_id}/returns/{return_id}`.

`POST /programs/{program_id}/returns/{return_id}/complete`  
Body: `{ "resolution": "REFUND" | "REPLACEMENT", "replacement_build_lot_id": null|"...", "replacement_serial_number": null|"SN999", "replacement_build_tag": null|"A17B" }`  
Response: same shape as `GET /programs/{program_id}/returns/{return_id}`.

### Quality campaigns (Ops only)

`POST /programs/{program_id}/quality_campaigns`  
Body: `{ "campaign_type": "SHIP_HOLD" | "RECALL", "build_tag_prefix": "A17" }`  
Response: `{ "quality_campaign_id": "...", "campaign_type": "...", "campaign_status": "OPEN", "build_tag_prefix": "..." }`

`GET /programs/{program_id}/quality_campaigns/{quality_campaign_id}`  
Response: `{ "quality_campaign_id": "...", "campaign_type": "...", "campaign_status": "...", "build_tag_prefix": "..." }`

`POST /programs/{program_id}/quality_campaigns/{quality_campaign_id}/escalate`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/quality_campaigns/{quality_campaign_id}`.

`POST /programs/{program_id}/quality_campaigns/{quality_campaign_id}/resolve`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/quality_campaigns/{quality_campaign_id}`.

`POST /programs/{program_id}/quality_campaigns/{quality_campaign_id}/close`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/quality_campaigns/{quality_campaign_id}`.

### Alerts

`GET /programs/{program_id}/alerts?alert_status=...&alert_type=...&customer_id=...&payment_id=...&tradein_id=...&claim_id=...`  
Response: `{ "alerts": [ { "alert_id": "...", "alert_type": "...", "alert_status": "...", "opened_ops_run_index": 0, "customer_id": null|"...", "order_id": null|"...", "device_id": null|"...", "payment_id": null|"...", "tradein_id": null|"...", "quality_campaign_id": null|"...", "claim_id": null|"..." } ] }`

`GET /programs/{program_id}/alerts/{alert_id}`  
Response: `{ "alert_id": "...", "alert_type": "...", "alert_status": "...", "opened_ops_run_index": 0, "customer_id": null|"...", "order_id": null|"...", "device_id": null|"...", "payment_id": null|"...", "tradein_id": null|"...", "quality_campaign_id": null|"...", "claim_id": null|"..." }`

`POST /programs/{program_id}/alerts/{alert_id}/acknowledge`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/alerts/{alert_id}`.

`POST /programs/{program_id}/alerts/{alert_id}/resolve`  
Body can be empty.  
Response: same shape as `GET /programs/{program_id}/alerts/{alert_id}`.
