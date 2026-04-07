# PoolPass Shuttle Ops API

This API is for a rideshare “event corridor” product where most rides are really seat bookings on shared shuttles. The external client experience is simple: a rider drafts a booking, submits it into the queue, gets dispatched to a driver-shuttle, then starts and completes. The part that gets tricky (in real life) is that these bookings can be prepaid either by a partner-issued seat pass or by a rider wallet, and ops needs a clean way to pause the city, clean up stale requests, and fix mistakes without quietly breaking balances.

Everything is hub-scoped. A `hub` is basically a city/event footprint. Nothing is shared between hubs, and IDs from one hub never work in another.

## The shape of a hub

A hub is created with a `name`. Reading a hub is how clients learn the current operating mode and the one number everyone uses for pricing pool seats. You'll see the hub's `id`, `posture`, its `ops_run_index`, and `pool_seat_price_cents` (it starts at 800 cents).

Ops uses `ops_run_index` as a visible “tick counter” for batch operations. It goes up only when ops explicitly runs the job.

## Posture: when the hub is operating vs frozen

Posture is intentionally small and blunt:

- `NORMAL`: riders can submit, dispatch, and start rides.
- `SAFETY_HOLD`: the city is frozen for safety/ops reasons.

In `SAFETY_HOLD`, riders can still create drafts and edit drafts, but the queue doesn’t move. Posting ride events that would activate or advance service (`SUBMIT`, `DISPATCH`, `START`) is blocked with `ERR_HUB_POSTURE_RESTRICTED`.

Putting the hub into `SAFETY_HOLD` also changes what riders see on existing active rides:
- Any ride that was `REQUESTED` becomes `ON_HOLD` with `hold_reason="HUB_SAFETY_HOLD"`.
- Any ride that was `DISPATCHED` becomes `ON_HOLD` with `hold_reason="HUB_SAFETY_HOLD"` and its `driver_id` drops off (the driver gets their seats back).
- Importantly, HUB safety holds preserve the ride’s place in line: the ride keeps its `request_seq`, and any prepaid fields (`wallet_charge_cents`, `pass_seats_applied`) remain intact.

When the hub posture returns to `NORMAL`, rides held only for `HUB_SAFETY_HOLD` automatically re-enter the queue: they return to `REQUESTED` (same `request_seq`, same prepaid fields). Holds caused by passes work differently (more on that below).

Ops changes posture via `POST /hubs/:hub_id/posture` and typically includes a short `note` for audit.

## Riders and wallets

A rider is created with a `name`. In this v1, riders can also be created with an optional `wallet_balance_cents` (it starts at or above zero). Wallet balances never go negative.

For pool bookings, the wallet charge is always derived from the hub’s seat price: `pool_seat_price_cents` is 800 cents to start, so a 2-seat booking charges 1600 cents, 6 seats charges 4800 cents, and so on.

Reading a rider returns `wallet_balance_cents`.

## Drivers: shuttles with seat capacity

Drivers represent the shuttle operators. Creating a driver accepts a `name` and a `seat_capacity`. Drivers have a `status` (`ACTIVE` or `SUSPENDED`) and a client-visible `seats_assigned` that reflects how many seats are currently reserved across the driver’s `DISPATCHED` and `IN_PROGRESS` rides.

Ops changes a driver via `POST /hubs/:hub_id/drivers/:driver_id/events` with an `event_type`:
- `SUSPEND` (with a `reason`)
- `REINSTATE` (often with a short `note`)

A suspended driver can’t take new dispatches. Suspending a driver also immediately requeues any rides that were `DISPATCHED` to them (the ride drops back to `REQUESTED` and the driver’s seats are released). In-progress rides aren’t yanked; they can finish.

## Passes: partner-funded seats

A pass is a bundle of seat credits issued by a partner. Creating a pass accepts:
- `partner_ref` (opaque partner identifier like “EVT-1”)
- `owner_rider_id`
- `total_seats`

A pass is either `ACTIVE` or `SUSPENDED`, and it always shows `seats_remaining`. A pass can only be used by its `owner_rider_id`.

Ops updates a pass via `POST /hubs/:hub_id/passes/:pass_id/events` with an `event_type`:
- `TOP_UP` (with `added_seats` and an optional `note`)
- `SUSPEND` (with a `reason`)
- `REINSTATE` (optional `note`)
- `TRANSFER` (with `to_rider_id` and optional `note`)

Transfers are meant to move a “clean” pass: if the pass was tied up in open rides, those seats are released first.

Suspended passes can’t fund rides. “Pass holds” also behave differently from hub safety holds:
- When a pass becomes unusable for an open ride (because of `SUSPEND` or `TRANSFER`), the ride moves to `ON_HOLD` with `hold_reason="PASS_SUSPENDED"` or `hold_reason="PASS_TRANSFERRED"`.
- Any prepaid fields coming from that pass are unwound: `pass_seats_applied` becomes 0 and the pass’s `seats_remaining` increases accordingly.
- The ride is removed from the queue: `request_seq` is cleared (set back to null). The idea is that riders need to re-confirm payment before they’re queued again.

These pass-related holds do not auto-reserve seats again when the pass is reinstated. Re-entering the queue happens through resubmission.

## Rides: booking lifecycle as events

A ride is created in `DRAFT` and is owned by a rider (`rider_id`). In v1, `kind` is always `"POOL"`. A ride has:
- `seat_count`
- `payment_mode` (`WALLET_ONLY`, `PASS_ONLY`, `PASS_THEN_WALLET`)
- optional `pass_id` (required for `PASS_ONLY` and `PASS_THEN_WALLET`)
- optional `rider_note` (a small note ops can see)
- `status`
- `version`

For visibility (and to keep customer messaging honest), a non-draft ride exposes how it was prepaid:
- `wallet_charge_cents`
- `pass_seats_applied`

Only one active ride per rider exists at a time. “Active” here means anything in the live flow (`REQUESTED`, `DISPATCHED`, `IN_PROGRESS`, `ON_HOLD`, or `WAITLISTED`). Drafts don’t count as active.

### Edits and versioning

Rides are versioned. Updates use `If-Match` with the current `version`. Calls without `If-Match` get `ERR_MISSING_IF_MATCH`. Mismatches get `ERR_VERSION_CONFLICT`. Successful updates bump `version`.

Edits are only allowed while a ride is not in the active queue: `DRAFT`, `WAITLISTED`, or `ON_HOLD`. Trying to edit a `REQUESTED` or later ride returns `ERR_INVALID_STATE`.

Editing is treated as “starting over”: the ride becomes `DRAFT`, clears `request_seq`, clears `hold_reason`, drops `driver_id`, and resets `wallet_charge_cents` and `pass_seats_applied` to 0. If the ride had prepaid amounts (common for `ON_HOLD` due to hub posture), those amounts are refunded as part of that reset.

### Submitting and prepaying

Submitting is a ride event. Clients post to `POST /hubs/:hub_id/rides/:ride_id/events` with `event_type="SUBMIT"`.

Submitting is when prepayment happens:

- `WALLET_ONLY`: the wallet is charged at the seat price (800 cents per seat), and the ride enters `REQUESTED`.
- `PASS_ONLY`: if the pass has enough seats, those seats are applied and the ride enters `REQUESTED`. If the pass is short, the ride enters `WAITLISTED` instead and does not consume seats yet.
- `PASS_THEN_WALLET`: the pass is applied first, then the wallet covers any remaining seats. This split happens as a single outcome. If wallet coverage is required and the wallet can’t cover it, the submit fails with `ERR_WALLET_INSUFFICIENT_FUNDS` and you won’t see partial seat consumption or partial charges.

Submitting is blocked in `SAFETY_HOLD` with `ERR_HUB_POSTURE_RESTRICTED`.

### Dispatching, starting, completing

Dispatching is a ride event with `event_type="DISPATCH"` and a `driver_id`. It’s valid only from `REQUESTED`. Dispatch fails with:
- `ERR_DRIVER_SUSPENDED` if the driver isn’t `ACTIVE`
- `ERR_DRIVER_CAPACITY_EXCEEDED` if the driver’s `seat_capacity` would be exceeded

Starting is `event_type="START"` and moves a `DISPATCHED` ride to `IN_PROGRESS`. Starting is blocked in `SAFETY_HOLD` with `ERR_HUB_POSTURE_RESTRICTED`.

Completing is `event_type="COMPLETE"` and moves an `IN_PROGRESS` ride to `COMPLETED`, freeing the driver’s reserved seats.

### Canceling

Canceling is `event_type="CANCEL"` and includes `cancel_by` (`RIDER`, `DRIVER`, `OPS`) and a `cancel_reason` (common values include `RIDER_CHANGED_MIND`, `OPS_STALE`, `OPS_UNRESOLVED`). Cancels are allowed from `DRAFT`, `REQUESTED`, `DISPATCHED`, `WAITLISTED`, and `ON_HOLD`.

Cancels before `START` refund prepayment: pass seats are returned and wallet charges are credited back. Cancels after `START` aren’t supported in v1 and return `ERR_INVALID_STATE`.

### Adjustments and voids (ops corrections)

After a ride is `COMPLETED`, ops sometimes needs to correct billing without mutating history. This is done with ride events:

- `event_type="ADJUST"` includes `direction` (`CREDIT` or `DEBIT`), `amount_cents`, and an optional `note`. Adjustments create an `adjustment_id` and appear on the ride in a small `adjustments` list where each adjustment shows `adjustment_id`, `direction`, `amount_cents`, and `status` (`ACTIVE` or `VOIDED`).
- `event_type="VOID_ADJUSTMENT"` includes `adjustment_id` and an optional `reason`. Voiding is a true undo: it reverses the wallet impact and marks the adjustment `VOIDED`. If undoing would overdraw the wallet, the void fails with `ERR_WALLET_INSUFFICIENT_FUNDS` and the adjustment stays `ACTIVE`.

Voiding an entire ride is `event_type="VOID"` with a `void_reason`. It’s for “this ride never happened” corrections and is only valid from `COMPLETED`. Voiding refunds the ride’s prepayment (returning pass seats and wallet charges), but it is blocked while the ride has any non-voided adjustments; that returns `ERR_DEPENDENCY_EXISTS`.

## run_ops: explicit batch processing

Ops runs the batch job via `POST /hubs/:hub_id/run_ops`. This increments `ops_run_index` and performs two visible behaviors:

1. Waitlist promotion: `WAITLISTED` rides are promoted into `REQUESTED` when their pass has enough seats. Promotions consume seats at promotion time. When multiple waitlisted rides are competing, the one with the lower `request_seq` is promoted first.
2. Cleanup: rides that sit unchanged through two ops runs are auto-cancelled.
   - `REQUESTED`, `DISPATCHED`, and `ON_HOLD` rides held for `HUB_SAFETY_HOLD` are cancelled as `cancel_by="OPS"` and `cancel_reason="OPS_STALE"`.
   - `ON_HOLD` rides held for pass reasons (`PASS_SUSPENDED` or `PASS_TRANSFERRED`) are cancelled as `cancel_reason="OPS_UNRESOLVED"`.
   - `WAITLISTED` rides are excluded from stale cleanup (they can legitimately wait).

## Versioning and the response envelope

PoolPass gets hit by retries constantly (mobile networks, ops UIs, drivers tapping twice). The API stays predictable by failing stale writes loudly and by keeping response shapes consistent for clients.

Edits use `If-Match` as described above.

All responses use the same envelope with `response_type` and `data`. On errors, `response_type="error"` and `data` includes `error_code` plus a human `message`.

## Endpoints

| Method | Path |
|--------|------|
| POST | /hubs |
| GET | /hubs/:hub_id |
| POST | /hubs/:hub_id/posture |
| POST | /hubs/:hub_id/run_ops |
| POST | /hubs/:hub_id/riders |
| GET | /hubs/:hub_id/riders/:rider_id |
| POST | /hubs/:hub_id/drivers |
| GET | /hubs/:hub_id/drivers/:driver_id |
| POST | /hubs/:hub_id/drivers/:driver_id/events |
| POST | /hubs/:hub_id/passes |
| GET | /hubs/:hub_id/passes/:pass_id |
| POST | /hubs/:hub_id/passes/:pass_id/events |
| POST | /hubs/:hub_id/rides |
| GET | /hubs/:hub_id/rides/:ride_id |
| PUT | /hubs/:hub_id/rides/:ride_id |
| POST | /hubs/:hub_id/rides/:ride_id/events |

## Appendix: Tokens

### Ride status values
DRAFT, REQUESTED, DISPATCHED, IN_PROGRESS, COMPLETED, CANCELLED, VOIDED, WAITLISTED, ON_HOLD

### Hold reasons
HUB_SAFETY_HOLD, PASS_SUSPENDED, PASS_TRANSFERRED

### Pass status values
ACTIVE, SUSPENDED

### Driver status values
ACTIVE, SUSPENDED

### Event types
SUBMIT, DISPATCH, START, COMPLETE, CANCEL, ADJUST, VOID_ADJUSTMENT, VOID

### Error codes
ERR_BAD_REQUEST  
ERR_NOT_FOUND  
ERR_MISSING_IF_MATCH  
ERR_VERSION_CONFLICT  
ERR_HUB_POSTURE_RESTRICTED  
ERR_INVALID_STATE  
ERR_CONSTRAINT_VIOLATION  
ERR_PASS_SUSPENDED  
ERR_PASS_NOT_OWNED  
ERR_WALLET_INSUFFICIENT_FUNDS  
ERR_DRIVER_SUSPENDED  
ERR_DRIVER_CAPACITY_EXCEEDED  
ERR_DEPENDENCY_EXISTS  
ERR_DUPLICATE_ACTIVE_RIDE
