# Fine-Watch Boutique API — Product Requirements Document

## 1. Introduction

This document specifies the back-office platform for a fine-watch boutique that both sells scarce, authenticated timepieces and services them at its own bench. The business has two intertwined problems. First, desirable references arrive in ones and twos, far below demand, so the boutique cannot simply "sell freely" — it must ration each arriving piece against a ranked list of waiting clients and hold an offer open for a fixed window before moving on. Second, money and merchandise flow in both directions: clients trade in or consign pieces for store credit, finance purchases through layaway, and pay for repairs in installments, while the boutique must be able to reverse a settlement cleanly the day a serial turns out to be counterfeit.

The platform is therefore a single system of record that unifies inventory and authentication, a bench-scheduling and repair-ticketing workflow, a waitlist-and-allocation engine, trade-in / consignment intake, layaway financing, warranty and insurance appraisal, and an append-only provenance trail for every physical watch. Two valuation philosophies coexist deliberately — a condition-depreciated market value and a condition-blind insurance-replacement value — and the same store-credit ledger must stay reconciled across trade-ins, consignments, layaway deposits, cancellations, and inauthenticity clawbacks. Every mutating action is expected to be immediately consistent: a watch freed by a defaulted layaway is offered to the next waiting client within the same request, and a piece flagged as inauthentic unwinds the plans and settlements that depended on it before the response is returned.

The remainder of this document defines the global contracts every endpoint honors (Section 2), the business workflows and their scattered rules (Section 3), the endpoint catalogue (Section 4), and the error-code catalogue (Section 5).

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID`, identifying the caller, and `X-User-Role`, naming the caller's role. If either header is missing, or `X-User-Role` is not one of the three recognized roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the headers are well-formed but the role is not permitted to perform the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

There are exactly three roles, spelled precisely as follows: `Associate`, `Client`, and `Watchmaker`.

- When `X-User-Role` is `Associate`, `X-User-ID` is an opaque operator identifier that is not tied to any persisted entity. The server may record it as narrative detail on a provenance event, but it never compares it to any entity's `id`. Associates are the boutique's staff and drive inventory, authentication, allocation, appraisal, trade-in and consignment administration, layaway administration, and the logical clock.
- When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Customer`; ownership checks on any resource that references a customer compare that resource's `customer_id` field to `X-User-ID`. A client acts on their own waitlist entries, layaway plans, service collections and payments, and trade-in/consignment acceptances.
- When `X-User-Role` is `Watchmaker`, `X-User-ID` is the `id` of the acting `Watchmaker`; ownership checks on a service ticket compare the ticket's `watchmaker_id` field to `X-User-ID`. A watchmaker works their own bench tickets — diagnosing and finishing them.

The authoritative per-endpoint permission map is the Authorized Role(s) column of Section 4.

### 2.2. API Response Structure

#### Standard Success Response Format

All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z",
    "limit": 10,
    "offset": 0,
    "total_count": 100,
    "has_more": true
  },
  "response_type": "object" | "array",
  "data": { }
}
```

- The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`.
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits.
- The `response_type` is either "object" for a single resource or "array" for a list of resources.
- The `data` field contains the resource object or an array of resource objects. For 2xx responses with no data, it contains an empty object. Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field.
- Pagination-related fields in `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for list endpoints.

#### Standard Error Response Format

All error API responses (4xx status codes) follow this standard envelope format:

```json
{
  "meta": {
    "api_request_id": "req_RANDOMALPHANUM123456",
    "api_request_timestamp": "2025-05-24T10:30:00.123Z"
  },
  "response_type": "error",
  "data": {
    "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
    "message": "A human-readable explanation of the error."
  }
}
```

- The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`.
- The `error_id` is a unique, machine-readable string that identifies the specific error.
- The `message` provides a human-readable explanation of what went wrong.

### 2.3. Pagination

All list endpoints accept two query parameters, `limit` and `offset`. `limit` defaults to 10, must be at least 1, and may not exceed 100. `offset` defaults to 0 and must be at least 0. Results are returned sorted by `created_at` in ascending order (oldest first). For every list response, the `meta` object carries `limit`, `offset`, `total_count` (the total number of records matching the query before pagination), and `has_more` (true when records beyond the current page remain).

### 2.4. Resource Identity, Versioning, and Timestamps

Every resource is assigned a server-minted `id` that is a UUID with no type prefix; clients never supply it. Most resources also carry a `created_at` timestamp (set once at creation), an `updated_at` timestamp (refreshed on every mutation), and an integer `version` that begins at 1 and increases by one on each mutation. All timestamps are ISO 8601 UTC values with three fractional digits.

One resource is deliberately lighter: a `ProvenanceEvent` is an append-only historical record and carries only `id` and `created_at`. It has no `updated_at` and no `version`, because it is never mutated after being written. Wherever this document speaks of "bumping the version" or "refreshing `updated_at`," it refers to the mutated business entity (typically the `Watch`), never to the provenance events appended alongside.

### 2.5. Monetary Precision and Rounding

All monetary amounts are stored and returned as integer cents. Every calculation that produces a monetary figure — appraisals, trade-in and consignment credit, service quotes, layaway installment schedules, and cancellation refunds — evaluates in real arithmetic and then rounds the final figure to the nearest whole cent using round-half-up (a value ending in exactly half a cent rounds away from zero). The lone exception is the layaway installment split, which uses floor division for the per-installment amount and lets the final installment absorb the remainder, as detailed in Section 3.4. A customer's `store_credit_cents` balance and a layaway plan's `remaining_cents` are never allowed to fall below zero.

### 2.6. The Logical Clock

Time in this system is a logical clock, not wall-clock time. Every deadline, expiry, and appointment comparison — offer windows, layaway grace periods, and bench-appointment validity — reads from this clock. On server startup the clock reads exactly `2026-07-01T00:00:00Z`, and before any set operation it stays fixed at that default and never falls back to real time. An administrative test-driving capability, reserved to `Associate`, advances the clock to a supplied instant via the `to_iso8601` field; thereafter all temporal comparisons use the most recently set value.

### 2.7. Optimistic Concurrency on Watch Re-Appraisal

Creating an appraisal against a watch is guarded by optimistic concurrency on the watch's `version`. The appraisal-create request must include `expected_watch_version` as a required field carrying the client's last observed `version` of the target `Watch`. If `expected_watch_version` is omitted from the request body, the request is rejected with `ERR_VERSION_REQUIRED` (HTTP 400). If it is present but does not equal the watch's current `version` — because some other writer has authenticated, flagged, or re-appraised the watch since the client last read it — the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Because each successful appraisal supersedes the prior `current_appraisal_id` and itself bumps the watch's `version`, this rule prevents a client from writing an appraisal against a watch state it has not actually observed. No other endpoint takes a version field.

### 2.8. Parallel State Machines and Cascade Consistency

Two of the core entities carry two independent state dimensions each. A `Watch` has an inventory `status` and, evolving separately, an `authentication_status`. A `ServiceTicket` has a workflow `status` and, evolving separately, a `payment_status`. These dimensions advance independently, and where an operation guards on both (collection, in particular) this document says so explicitly.

Several actions cascade across entities within the same request, and every secondary effect must land before the response returns:

- **The default-and-reoffer cascade.** When a layaway plan is defaulted, the plan leaves `ACTIVE`, which frees its reserved watch back to inventory, which — when the watch's model is allocation-controlled and a waiting client qualifies — in turn extends a fresh offer to the top-ranked eligible waitlist entry. This is a three-hop chain triggered by a single default action.
- **The inauthenticity-unwind cascade.** Flagging a watch as inauthentic drives a set of compensating effects on every dependent resource (voiding active layaways with a refund, reversing settled trade-ins with a clawback, cancelling open service tickets), detailed in Section 3.1.
- **The offer-compensation invariant.** When an outstanding offer is declined or lapses, the offered watch returns to stock so that the count of in-stock watches for that model is restored to exactly its pre-offer value.

Every side effect that mutates a `Watch` (authentication, flagging, appraisal) refreshes that watch's `updated_at` and increases its `version` by one. Provenance events are appended as a byproduct of these operations but do not themselves carry versions.

### 2.9. The Store-Credit Ledger

Each `Customer` carries a `store_credit_cents` balance, denominated in integer cents, that starts at 0 and is never negative. It is a running ledger touched from several directions: it is credited when a trade-in or consignment settles, drawn down when it funds a layaway deposit, credited again by a layaway cancellation refund, credited in full when a layaway is voided by an inauthenticity flag, and clawed back when a settled trade-in is reversed. The reversal clawback is the exact counterpart of the settlement credit: the same `quoted_credit_cents` that was added on settlement is subtracted on reversal, so the ledger closes to where it began.

### 2.10. Validation Ordering and Nested-Resource Resolution

Requests are validated in a fixed priority order, and the first failing check determines the returned error. Authentication (`ERR_UNAUTHENTICATED`, 401) is checked first; then authorization against the endpoint's permitted roles (`ERR_UNAUTHORIZED`, 403); then existence of every path-referenced and foreign-key-referenced resource, resolved left to right along the URL and then across referenced ids (`ERR_NOT_FOUND`, 404); then request-body well-formedness — required fields present, enum values recognized, integer fields non-negative (`ERR_VALIDATION`, 400). Only after these four universal gates pass are the domain-specific business rules evaluated. Among the business rules, state-validity checks (`ERR_INVALID_STATE`, 409) and the specific business constraints described throughout Section 3 apply; where several business constraints could fire on one endpoint, the endpoint's own narrative in Section 3 names which condition is decisive.

## 3. Business Logic & Workflows

### 3.1. Catalog, Inventory Intake, Authentication, and Flagging

The boutique's reference data is created by associates. A `Customer` is registered with a `full_name`, an `email` (which is unique), an optional `phone`, and an optional `kyc_verified` flag; the balance `store_credit_cents` is initialized to 0 and is never client-supplied. A catalog `WatchModel` records its `brand`, `reference_number`, human-readable `display_name`, and `msrp_cents`, together with an optional `market_premium_bps` (the secondary-market scarcity premium over MSRP, in basis points, defaulting to 0), an optional `allocation_controlled` flag (defaulting to false; when true, arriving watches of this model are rationed off the waitlist rather than sold freely), and an optional `lifecycle` that is either `ACTIVE` (the default, accepting waitlist joins) or `DISCONTINUED`. A `Watchmaker` is created with a `display_name`, an optional `specialties` array (the service types they handle, defaulting to empty), and an optional `active` flag (defaulting to true) indicating whether they currently accept new tickets.

A physical `Watch` is taken into inventory with its `model_id`, a `serial_number`, a `condition_grade` (one of `NEW`, `MINT`, `EXCELLENT`, `GOOD`, or `FAIR`), and a `list_price_cents` asking price, plus optional `has_box_papers` (whether the full set of box and papers is present, defaulting to false), `acquisition_cost_cents` (the boutique's cost basis, defaulting to null), and `is_loaner` (defaulting to false; a loaner is a service-loan unit, not for sale, that occupies loan intervals). On intake the watch is born with inventory `status` of `IN_STOCK`, `authentication_status` of `UNVERIFIED`, a `source` of `PURCHASE`, a null `current_appraisal_id`, and an `INTAKE` provenance event is appended. The `serial_number` must be unique across all watches; a collision is rejected with `ERR_SERIAL_DUPLICATE` (HTTP 409), and this same uniqueness rule guards the serial minted when a trade-in or consignment settles.

Authentication moves the watch's `authentication_status` from `UNVERIFIED` to `AUTHENTICATED`; it is permitted only when the watch is currently `UNVERIFIED`, otherwise `ERR_INVALID_STATE`. A successful authentication appends an `AUTHENTICATED` provenance event and increases the watch's `version` by one. Authentication is the gate that unlocks the watch for commerce and service: a watch cannot be offered off the waitlist, reserved for layaway, or opened for service unless its `authentication_status` is `AUTHENTICATED`.

Flagging a watch inauthentic drives its `authentication_status` to the terminal `FLAGGED` state and may be applied when the watch is currently either `UNVERIFIED` or `AUTHENTICATED`. An optional `reason` may accompany the flag. Reaching `FLAGGED` appends a `FLAGGED` provenance event, increases the watch's `version` by one, and triggers a full inauthenticity unwind on every dependent resource, all within the flagging request:

- Any `ACTIVE` `LayawayPlan` whose `watch_id` is this watch is voided — its status moves `ACTIVE → VOIDED` — and the entire `paid_cents` amount is refunded to the customer's `store_credit_cents`. This void is caused by the watch flagging, not by the customer.
- If this watch was a trade-in intake (its `source` is `TRADE_IN` and a `SETTLED` `TradeInOffer` has its `resulting_watch_id` pointing at this watch), that offer is reversed — status `SETTLED → REVERSED` — and the customer's `store_credit_cents` is reduced by the offer's `quoted_credit_cents`, closing the ledger clawback.
- Any open `ServiceTicket` on this watch whose workflow `status` is `RECEIVED` or `DIAGNOSED` is cancelled — status to `CANCELLED` — returning the watch's inventory `status` from `IN_SERVICE` to `IN_STOCK` and releasing any reserved loaner interval.

Because flagging bumps the watch's `version`, any appraisal a client attempts afterward while still holding the pre-flag version will be refused by the concurrency rule of Section 2.7.

### 3.2. Appraisals and the Two Valuation Philosophies

An appraisal is a computed valuation snapshot for a single watch, created by an associate. The request supplies a `purpose` (`WARRANTY`, `INSURANCE`, or `SALE`), a `valuation_basis` (`MARKET` or `INSURANCE_REPLACEMENT`), and the `expected_watch_version` described in Section 2.7. At creation the watch's current `condition_grade` is captured onto the appraisal as `condition_grade_snapshot`, the valuation runs, the watch's `current_appraisal_id` is repointed to this newest appraisal (which supersedes all prior ones), an `APPRAISED` provenance event is appended, and the watch's `version` is increased by one. Prior appraisals remain discoverable through the watch's appraisal history, newest superseding.

The valuation computes two figures and then selects between them. First, a condition factor is read from the grade: `NEW` yields 1.00, `MINT` yields 0.95, `EXCELLENT` yields 0.88, `GOOD` yields 0.78, and `FAIR` yields 0.65. A box-and-papers premium of 0.08 applies when `has_box_papers` is true, and is 0 otherwise.

- The **market value**, `market_value_cents`, is the model's `msrp_cents` multiplied by the condition factor and then by one plus the box premium, rounded half-up to whole cents. It depreciates for wear.
- The **replacement value**, `replacement_value_cents`, is the model's `msrp_cents` multiplied by one plus `market_premium_bps` divided by 10000, rounded half-up to whole cents. It reflects retail plus scarcity and ignores condition entirely, so for a worn but scarce piece it yields the higher figure.

The `appraised_value_cents` recorded on the appraisal is `market_value_cents` when `valuation_basis` is `MARKET` (as used for `WARRANTY` and `SALE` purposes) and `replacement_value_cents` when `valuation_basis` is `INSURANCE_REPLACEMENT` (as used for `INSURANCE`).

### 3.3. The Waitlist, Allocation, and Offers

A `Customer` joins the waitlist for a model by creating a `WaitlistEntry` naming the `customer_id` and `model_id`, with an optional `priority_tier` (`STANDARD`, `PREMIER`, or `VIP`, defaulting to `STANDARD`) and an optional good-faith `deposit_cents` (defaulting to 0, where a larger deposit breaks priority ties). A new entry is born `WAITING`, with a null `allocated_watch_id` and null `offer_expires_at`. Two constraints guard the join: a model whose `lifecycle` is `DISCONTINUED` cannot be joined (`ERR_MODEL_DISCONTINUED`, 409), and a customer may hold only one non-terminal entry — one in `WAITING` or `OFFERED` — per model, a second attempt being rejected with `ERR_DUPLICATE_WAITLIST` (409).

Allocation is how a scarce authenticated watch reaches a waiting client. When an associate offers an in-stock watch, or when the default-and-reoffer cascade auto-offers one, the system selects the single best waiting entry for that watch's model. The candidate set is every `WaitlistEntry` in `WAITING` status whose `model_id` matches the watch's model and whose model's `lifecycle` is `ACTIVE`. Candidates are ranked by priority tier first, where `VIP` outranks `PREMIER`, which outranks `STANDARD`; ties within a tier are broken by higher `deposit_cents`; and any remaining tie is broken by earlier `created_at` (never by id). The highest-ranked candidate is selected. If the candidate set is empty, the offer is refused with `ERR_NO_ELIGIBLE_WAITLIST` (409). Offering additionally requires that the watch is currently `IN_STOCK` (else `ERR_WATCH_UNAVAILABLE`, 409) and that its `authentication_status` is `AUTHENTICATED` (else `ERR_WATCH_NOT_AUTHENTICATED`, 409).

A successful offer advances the selected entry `WAITING → OFFERED`, sets its `allocated_watch_id` to the watch, sets `offer_expires_at` to the current clock instant plus seven days, moves the watch's inventory `status` `IN_STOCK → OFFERED`, and appends an `ALLOCATED` provenance event. The offer stands open for that seven-day window.

The offered client then either accepts or declines. Accepting advances the entry `OFFERED → ALLOCATED` and the watch `OFFERED → RESERVED`, but only while the current clock reads strictly before `offer_expires_at`; an acceptance at or after that instant is rejected with `ERR_OFFER_EXPIRED` (409) and, in the same lazy step, the entry lapses `OFFERED → EXPIRED`, its `allocated_watch_id` is cleared, and the watch returns `OFFERED → IN_STOCK`. Declining advances the entry `OFFERED → DECLINED`, clears its `allocated_watch_id`, and returns the watch `OFFERED → IN_STOCK` under the compensating invariant that restores the model's in-stock count. Both the accept and decline actions may be driven by the acting `Client` or by an `Associate`.

### 3.4. Layaway Financing

A layaway reserves a watch while the client pays it off over time. Creating a plan names the `customer_id`, the `watch_id`, a `deposit_cents` down payment, a `term_months` count of monthly installments, and a `first_due_at` date for the first installment; an optional `use_store_credit` flag (defaulting to false) draws the deposit from the customer's balance rather than fresh funds. The target watch must be `IN_STOCK` (else `ERR_WATCH_UNAVAILABLE`, 409) and `AUTHENTICATED` (else `ERR_WATCH_NOT_AUTHENTICATED`, 409). On creation the plan snapshots the watch's `list_price_cents` as `total_price_cents`, records `paid_cents` equal to the deposit, moves the watch `IN_STOCK → RESERVED`, is born `ACTIVE`, and appends a `LAYAWAY_RESERVED` provenance event.

Two fiscal gates protect the deposit. The deposit must be at least twenty percent of the price — specifically, at least the price multiplied by 0.20 and rounded half-up to whole cents; a deposit below that floor is rejected with `ERR_DEPOSIT_TOO_LOW` (HTTP 422). And when `use_store_credit` is set, the customer's `store_credit_cents` must be at least the `deposit_cents`; if it is short, the request is rejected with `ERR_INSUFFICIENT_STORE_CREDIT` (422). When store credit is used, that deposit amount is deducted from the customer's balance.

The installment schedule is computed with a pinned rounding order. The financed amount is `total_price_cents` minus `deposit_cents`. The `per_installment_cents` is the financed amount divided by `term_months`, taking the floor (the largest whole cent not exceeding the quotient). The `final_installment_cents` is the financed amount minus `per_installment_cents` multiplied by `term_months` minus one — that is, the final installment absorbs the rounding remainder so that the first `term_months` minus one installments each equal `per_installment_cents` and the whole schedule reconciles exactly to the financed amount. The plan's `remaining_cents` is `total_price_cents` minus `paid_cents` and is never negative.

Installment payments carry an `amount_cents`. Each payment adds to `paid_cents` and recomputes `remaining_cents`. A payment may never push `paid_cents` above `total_price_cents`; an overpayment is rejected with `ERR_OVERPAYMENT` (422). When a payment brings `paid_cents` to exactly `total_price_cents`, the plan advances `ACTIVE → PAID_OFF`, sets `remaining_cents` to 0, and is then automatically fulfilled `PAID_OFF → FULFILLED`, which sells the watch by moving it `RESERVED → SOLD`.

A plan may leave `ACTIVE` down three other paths. Cancelling it (by the `Client` or an `Associate`) moves it `ACTIVE → CANCELLED`, returns the watch `RESERVED → IN_STOCK`, and refunds the client: a restocking fee equal to `total_price_cents` multiplied by 0.05 and rounded half-up is computed, and the refund is `paid_cents` minus that fee but never below zero, credited to the customer's `store_credit_cents`. Defaulting a plan (by an `Associate` only) moves it `ACTIVE → DEFAULTED`, but only once the current clock is at or after `first_due_at` plus ten days of grace; an attempt before that instant is rejected with `ERR_INVALID_STATE` (409). On default the `paid_cents` is forfeited to the boutique with no refund, and the watch is freed `RESERVED → IN_STOCK`; that freeing in turn auto-offers the watch to the top eligible waiting client when the model is allocation-controlled and an eligible entry exists. Finally, the void path `ACTIVE → VOIDED` is not called directly but is driven by the inauthenticity unwind of Section 3.1, refunding the full `paid_cents`.

### 3.5. Trade-In and Consignment

A client may bring in a piece for trade-in or consignment. An associate quotes it by creating a `TradeInOffer` naming the `customer_id`, the incoming piece's `incoming_brand`, `incoming_reference`, and `serial_number`, an `est_model_msrp_cents` estimate of its model MSRP, a `condition_grade`, and a `disposition` of either `TRADE_IN` or `CONSIGNMENT`, plus an optional `has_box_papers` flag (defaulting to false). The offer is born `QUOTED`, with a null `resulting_watch_id`.

At quote time the incoming piece's market value is appraised: `appraised_market_cents` is `est_model_msrp_cents` multiplied by the condition factor (the same grade table as appraisals — 1.00, 0.95, 0.88, 0.78, 0.65 for `NEW`, `MINT`, `EXCELLENT`, `GOOD`, `FAIR`) and then by one plus a 0.08 box premium when `has_box_papers`, rounded half-up. The credit then diverges by disposition:

- For a `TRADE_IN`, the `commission_rate_bps` is null and the `quoted_credit_cents` is the appraised market value multiplied by 0.70 (a flat seventy percent), rounded half-up — paid instantly as store credit on settlement.
- For a `CONSIGNMENT`, a tiered commission applies: the `commission_rate_bps` is 2000 basis points when the appraised market value is at most 500000 cents, 1500 basis points when it is at most 2000000 cents, and 1000 basis points above that. The `quoted_credit_cents` is the appraised market value multiplied by one minus `commission_rate_bps` divided by 10000, rounded half-up. Consignment therefore yields more credit than a trade-in of the same piece, but is realized as proceeds after commission rather than instant credit.

The client accepts a quote to move the offer `QUOTED → ACCEPTED` (the offer must be `QUOTED`, else `ERR_INVALID_STATE`). An offer may also be declined out of `QUOTED`, terminating it `QUOTED → DECLINED`. Settlement, driven by an `Associate`, moves an accepted offer `ACCEPTED → SETTLED`. For a consignment settlement the customer's `kyc_verified` must be true, otherwise `ERR_KYC_REQUIRED` (409). Settlement mints a new inventory `Watch` from the incoming `serial_number` — subject to the same cross-inventory serial-uniqueness rule (`ERR_SERIAL_DUPLICATE`, 409) — sets its `source` to `TRADE_IN` or `CONSIGNMENT`, and places it `IN_STOCK` for a trade-in but directly `CONSIGNED` for a consignment. The offer's `resulting_watch_id` is set to the minted watch, the customer's `store_credit_cents` is increased by `quoted_credit_cents`, and a `TRADE_IN_INTAKE` provenance event is appended. Should that minted watch later be flagged inauthentic, the settlement reverses `SETTLED → REVERSED` and the same `quoted_credit_cents` is clawed back, as described in Section 3.1.

### 3.6. Service Tickets, Bench Scheduling, and Loaners

A service ticket books a watch onto a watchmaker's bench. Opening one names the `watch_id`, the owner's `customer_id`, the assigned `watchmaker_id`, a `service_type` (`BATTERY`, `MOVEMENT_OVERHAUL`, or `WATER_RESISTANCE`), and a bench appointment window given by `appt_start` (inclusive) and `appt_end` (exclusive). Optional inputs shape the quote and the loan: `movement_complexity` (`STANDARD`, `CHRONOGRAPH`, or `GRAND_COMPLICATION`, defaulting to `STANDARD`), `water_resistance_target_m` (the target metres for a water-resistance job, defaulting to null), and `parts_cost_cents` (defaulting to 0). A loaner may optionally be reserved for the customer by naming a `loaner_watch_id` together with a `loan_start` (inclusive) and `loan_end` (inclusive), all defaulting to null. Opening a ticket requires the serviced watch to be `AUTHENTICATED` (else `ERR_WATCH_NOT_AUTHENTICATED`, 409); on success the watch moves `IN_STOCK → IN_SERVICE`, the ticket is born with workflow `status` `RECEIVED` and `payment_status` `UNPAID`, its `quoted_cents` still null, and its `amount_paid_cents` at 0.

Three scheduling gates protect the calendar, all evaluated against non-terminal tickets. The appointment must not be back-dated: `appt_start` must be at or after the current clock, otherwise `ERR_APPOINTMENT_IN_PAST` (HTTP 422). The bench must be free: treating each appointment as a half-open window and requiring a buffer of thirty minutes between jobs on the same `watchmaker_id`, a new booking conflicts with an existing one unless the new start is at or after the existing end plus thirty minutes, or the existing start is at or after the new end plus thirty minutes — so a gap of exactly thirty minutes is allowed, and any tighter spacing is rejected with `ERR_WATCHMAKER_UNAVAILABLE` (409). The loaner must be free: treating each loan as a closed interval on the same `loaner_watch_id`, a new loan conflicts with an existing one when the new start falls before the existing end and the existing start falls before the new end — so two loans that merely touch at an endpoint (one ending exactly when the next begins) do not conflict, while any true overlap is rejected with `ERR_LOANER_UNAVAILABLE` (409).

The bench workflow runs in stages driven by the assigned `Watchmaker`. Diagnosis moves the ticket `RECEIVED → DIAGNOSED` and computes the `quoted_cents`. The quote is built in a fixed order: labor first, then parts, then a water surcharge, then a clamp. Labor is a base amount for the service type — 8000 cents for `BATTERY`, 60000 cents for `MOVEMENT_OVERHAUL`, 25000 cents for `WATER_RESISTANCE` — multiplied by a complication factor of 1.0 for `STANDARD`, 1.5 for `CHRONOGRAPH`, or 2.5 for `GRAND_COMPLICATION`. For a water-resistance job only, a surcharge adds 5000 cents for each 100 metres of `water_resistance_target_m`, rounding the metre figure up to the next whole 100 before multiplying (for example, a 150-metre target counts as two 100-metre blocks); for any other service type the surcharge is zero. The raw total is labor plus `parts_cost_cents` plus the water surcharge, rounded half-up, and then clamped to lie between a floor of 12000 cents and a ceiling of 500000 cents. Finishing the service moves the ticket `DIAGNOSED → READY` and appends a `SERVICED` provenance event on the watch.

Payments on a ticket carry an `amount_cents` and accumulate into `amount_paid_cents`; a ticket must already be quoted (in `DIAGNOSED` or `READY`) to accept payment. A payment that would carry `amount_paid_cents` above `quoted_cents` is rejected as an overpayment (`ERR_OVERPAYMENT`, 422). While the running total stays below the quote the `payment_status` sits at `PARTIALLY_PAID`; when it reaches exactly `quoted_cents` the `payment_status` becomes `PAID`. Collection is the one action gated on both ticket dimensions: it moves the workflow `READY → COLLECTED` only when the ticket is `READY` and its `payment_status` is `PAID`, rejecting an unpaid collection with `ERR_PAYMENT_NOT_COMPLETE` (409). On collection the watch returns `IN_SERVICE → IN_STOCK` and any loaner interval is released. Separately, if the serviced watch is flagged inauthentic while a ticket is still `RECEIVED` or `DIAGNOSED`, the system cancels the ticket to `CANCELLED`, returns the watch to `IN_STOCK`, and releases the loaner, as covered in Section 3.1.

### 3.7. Provenance

Every physical watch accumulates an append-only provenance history. Each `ProvenanceEvent` records the `watch_id` it belongs to, an `event_type` drawn from `INTAKE`, `AUTHENTICATED`, `FLAGGED`, `APPRAISED`, `SERVICED`, `LAYAWAY_RESERVED`, `ALLOCATED`, `TRADE_IN_INTAKE`, and `REVERSED`, a human-readable `detail`, and the `actor_role` responsible — one of `Associate`, `Client`, `Watchmaker`, or `system` (the last for effects caused by cascades rather than a direct caller). These events are written as the byproducts described throughout Section 3 — intake at inventory creation, authentication and flagging on the authentication actions, appraisal on valuation, allocation on offer, layaway reservation on plan creation, servicing on finish, and trade-in intake on settlement — and are never modified once written. The history for a watch is readable in `created_at` order and is paginated like any other list.

## 4. Endpoint Definitions

Creation endpoints that mint a new resource return HTTP 201; all other successful operations, including state transitions and payments, return HTTP 200. Every request and response body follows the envelope of Section 2.2, and the fields carried in each request are described in the Section 3 narratives rather than repeated here.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/customers` | Register a customer | Associate |
| GET | `/customers/{id}` | Get a customer (including store credit) | Associate, Client |
| POST | `/watch-models` | Create a catalog model | Associate |
| GET | `/watch-models/{id}` | Get a model | Associate, Client |
| POST | `/watchmakers` | Create a watchmaker (service bench) | Associate |
| GET | `/watchmakers/{id}` | Get a watchmaker | Associate, Client, Watchmaker |
| POST | `/watches` | Take a watch into inventory | Associate |
| GET | `/watches/{id}` | Get a watch | Associate, Client |
| GET | `/watches` | List/search watches | Associate, Client |
| POST | `/watches/{id}/authenticate` | Authenticate a watch | Associate |
| POST | `/watches/{id}/flag-inauthentic` | Flag a watch inauthentic (unwind cascades) | Associate |
| GET | `/watches/{id}/provenance` | Get a watch's provenance history | Associate, Client |
| POST | `/watches/{id}/appraisals` | Create an appraisal (OCC on watch version) | Associate |
| GET | `/watches/{id}/appraisals` | List appraisals for a watch | Associate, Client |
| POST | `/watches/{id}/offer` | Allocate an in-stock watch to the top eligible waitlist entry | Associate |
| POST | `/waitlist-entries` | Join the waitlist for a model | Associate, Client |
| GET | `/waitlist-entries/{id}` | Get a waitlist entry | Associate, Client |
| GET | `/waitlist-entries` | List/search waitlist entries | Associate, Client |
| POST | `/waitlist-entries/{id}/accept` | Accept an offer (reserves the watch) | Associate, Client |
| POST | `/waitlist-entries/{id}/decline` | Decline an offer (returns watch to stock) | Associate, Client |
| POST | `/service-tickets` | Open a service ticket (reserves bench + optional loaner) | Associate, Client |
| GET | `/service-tickets/{id}` | Get a service ticket | Associate, Client, Watchmaker |
| GET | `/service-tickets` | List/search service tickets | Associate, Client, Watchmaker |
| POST | `/service-tickets/{id}/diagnose` | Diagnose and quote the service | Watchmaker |
| POST | `/service-tickets/{id}/finish` | Mark the service ready for collection | Watchmaker |
| POST | `/service-tickets/{id}/collect` | Collect the serviced watch | Associate, Client |
| POST | `/service-tickets/{id}/payments` | Apply a payment to a service ticket | Associate, Client |
| POST | `/layaway-plans` | Open a layaway plan reserving a watch | Associate, Client |
| GET | `/layaway-plans/{id}` | Get a layaway plan | Associate, Client |
| GET | `/layaway-plans` | List/search layaway plans | Associate, Client |
| POST | `/layaway-plans/{id}/payments` | Apply an installment payment | Associate, Client |
| POST | `/layaway-plans/{id}/default` | Declare a layaway defaulted after grace | Associate |
| POST | `/layaway-plans/{id}/cancel` | Cancel a layaway (refund minus restock fee) | Associate, Client |
| POST | `/trade-in-offers` | Quote a trade-in or consignment | Associate |
| GET | `/trade-in-offers/{id}` | Get a trade-in/consignment offer | Associate, Client |
| GET | `/trade-in-offers` | List/search trade-in/consignment offers | Associate, Client |
| POST | `/trade-in-offers/{id}/accept` | Accept a quoted offer | Associate, Client |
| POST | `/trade-in-offers/{id}/settle` | Settle an accepted offer (mint watch, credit customer) | Associate |
| POST | `/_clock/set_current_utc` | Set the server logical clock | Associate |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_VALIDATION` | 400 |
| `ERR_SERIAL_DUPLICATE` | 409 |
| `ERR_DUPLICATE_WAITLIST` | 409 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_OFFER_EXPIRED` | 409 |
| `ERR_MODEL_DISCONTINUED` | 409 |
| `ERR_WATCH_NOT_AUTHENTICATED` | 409 |
| `ERR_KYC_REQUIRED` | 409 |
| `ERR_WATCHMAKER_UNAVAILABLE` | 409 |
| `ERR_LOANER_UNAVAILABLE` | 409 |
| `ERR_APPOINTMENT_IN_PAST` | 422 |
| `ERR_NO_ELIGIBLE_WAITLIST` | 409 |
| `ERR_WATCH_UNAVAILABLE` | 409 |
| `ERR_DEPOSIT_TOO_LOW` | 422 |
| `ERR_INSUFFICIENT_STORE_CREDIT` | 422 |
| `ERR_OVERPAYMENT` | 422 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_VERSION_REQUIRED` | 400 |
| `ERR_PAYMENT_NOT_COMPLETE` | 409 |
