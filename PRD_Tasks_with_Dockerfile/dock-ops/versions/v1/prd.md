# DockOps Hub API (v1)

DockOps is a small backend for cross-dock hubs that live and die by one thing: **staging space**. Every inbound unload consumes space. Every outbound pickup frees it. When the floor gets tight, the hub changes how it behaves so clients don’t accidentally schedule work that the building can’t physically absorb.

Everything in this API is scoped to a single `hub`. No cross-hub sharing.

The model is intentionally compact: you track a `consignment` (the shipment), the `dock_requests` (moves against it), and `holds` (why it can’t leave). Operations teams run `run_ops` as a predictable checkpoint to sweep staleness and close out cleanly finished work.

## Hubs and “what space is left”

A hub is created with a `name` and a `staging_capacity_units`. Reading a hub returns a few values clients actually care about:

- `staging_in_use_units`: units physically on the floor right now (what’s still on hand across consignments)
- `staging_reserved_units`: units the hub has already promised to receive soon (inbound requests that are scheduled but not yet completed)
- `staging_free_units`: what’s left after accounting for `staging_in_use_units` and `staging_reserved_units`
- `posture`: how conservative the hub is behaving right now
- `ops_run_index`: a monotone counter that bumps every time operations runs a checkpoint

The posture is derived from `staging_free_units`:

- `OPEN` is the normal mode.
- A hub is `CONGESTED` when free staging is at **20% of capacity or less** (fractions round down). It’s still running, but it starts pushing back on big inbound moves.
- When free staging hits **zero**, posture flips to `LOCKDOWN`.

`LOCKDOWN` is meant to stop the bleeding. In `LOCKDOWN`, **outbound moves are still allowed; inbound moves are blocked**, because outbound frees space and inbound consumes it.

Clients should treat `posture` and `staging_free_units` as immediately current. If something changes staging (a completion, a cancellation, or a correction), you’ll see it reflected on the next read.

## Consignments (the shipment you’re moving)

A consignment represents a shipment the hub expects to touch. Creating one accepts:

- `reference` (your external identifier)
- `declared_units` (how big the shipment is supposed to be)
- `commodity` (`GENERAL`, `COLD_CHAIN`, or `HAZMAT`)

A new consignment starts with `units_on_hand=0` and `status=PLANNED`. As work happens, you’ll see:

- `AT_HUB` when `units_on_hand` is greater than zero
- `RELEASED` when `units_on_hand` reaches zero *after* a receipt has happened
- `CLOSED` when ops has swept it as finished
- `VOIDED` when it was created in error and erased from active work

Consignments are “receipt-shaped” in v1: **each consignment is expected to be received once**. If a shipment shows up in pieces, it’s modeled as multiple consignments (usually the same `reference` with a suffix on the client side).

### Voiding a consignment

Voiding is for “this should not have existed.” A consignment can be voided only when nothing has been physically executed against it: `units_on_hand` is still zero, there are no dock requests beyond draft behavior, and there aren’t any active issues being tracked against it. When a consignment is voided, it’s treated as not schedulable and not actionable going forward.

## Dock requests (moves against a consignment)

A `dock_request` is a request to move units in or out of staging.

Creating one accepts:

- `consignment_id`
- `direction` (`INBOUND` or `OUTBOUND`)
- `units` (the planned units for this move)
- `priority` (`EXPEDITE`, `STANDARD`, `DEFERRED`)

A dock request starts as `DRAFT`. It also gets a `sequence` number that is monotone within a hub (it’s used as a stable tie-breaker when ops schedules a batch).

Dock request status is one of:
`DRAFT`, `SUBMITTED`, `SCHEDULED`, `ON_HOLD`, `DONE`, `CANCELLED`, `EXPIRED`, `VOIDED`.

### “One consignment, one open move”

To avoid conflicting instructions on a single shipment, DockOps treats a consignment as having **one open move** at a time: only one dock request in `SUBMITTED`, `SCHEDULED`, or `ON_HOLD` can exist per consignment. Drafts don’t count; they’re just sketches.

If a client tries to submit a second open move for the same consignment, the API responds with `ERR_CONSIGNMENT_BUSY`.

### Submitting a dock request

Submitting moves a request from `DRAFT` to `SUBMITTED`.

Inbound requests are posture-sensitive:

- In `LOCKDOWN`, inbound submissions are blocked.
- In `CONGESTED`, inbound submissions are capped to **one quarter of `staging_free_units` at the moment of submission** (fractions round down, minimum 1). This is meant to prevent a single inbound move from consuming the last usable floor space.

Outbound requests are shipment-sensitive:

- Outbound work is blocked while the consignment has any hold in `OPEN` status.
- Outbound work also can’t remove more than is available on hand.

### Scheduling (how ops turns “submitted” into an actual lineup)

Scheduling is done in one shot through a batch call. Clients send `dock_request_ids`, and the hub processes them in a deterministic order: **`EXPEDITE` first, then `STANDARD`, then `DEFERRED`, with `sequence` as the tie-breaker**.

The scheduling response is intentionally simple: `scheduled_ids` for what got lined up, and `rejected` entries that include a `dock_request_id` and an `error_code` for what didn’t.

Scheduling is where capacity becomes real for inbound moves:

- When an inbound request becomes `SCHEDULED`, its planned `units` immediately count toward `staging_reserved_units`.
- If an inbound request’s planned units don’t fit into `staging_free_units` at the moment it’s considered, it’s rejected as `ERR_CAPACITY_EXCEEDED`.

Outbound scheduling doesn’t reserve space (it frees it), but it still won’t schedule something that has become impossible (for example, if the consignment no longer has enough `units_on_hand` to satisfy the request).

### Completing a dock request

Completing a scheduled request is when the floor actually changes. Completion accepts an `actual_units` value and the API records `variance_units` on the dock request.

- For inbound completion, `actual_units` increases the consignment’s `units_on_hand`. Any inbound reservation is released at the same time.
- For outbound completion, `actual_units` decreases the consignment’s `units_on_hand`.

Capacity is enforced on completion too. If an inbound unload comes in larger than planned, the “extra” has to fit in whatever free staging was left. If it doesn’t, completion is rejected with `ERR_CAPACITY_EXCEEDED` and nothing changes.

#### Variance-triggered holds

Large variances are treated as operational risk. If the variance is **3 units or more** (in either direction), the hub automatically opens a `DAMAGE` hold with `source=AUTO_VARIANCE` and a `source_dock_request_id` back to the move that triggered it. When this happens, the completion response includes an `auto_hold_id` so clients can fetch the hold if they want to display it.

## Holds (why a consignment can’t leave)

A hold is a reason outbound work can’t proceed. Creating a hold accepts:

- `consignment_id`
- `kind` (`DOCS`, `DAMAGE`, `TEMPERATURE`, `CUSTOMS`)
- `note`

A hold starts as `status=OPEN` and has a `source` of `MANUAL` unless it was system-created from variance rules (`AUTO_VARIANCE`).

When a hold is opened, any outbound dock request that isn’t finished drops into `ON_HOLD`. Clearing the last open hold pops those requests back to `SUBMITTED` (they aren’t auto-scheduled; ops still has to line them up).

Holds have their own lifecycle:
`OPEN` → `CLEARED` (issue resolved) or `VOIDED` (hold was created in error).

## Corrections (voids that unwind real effects)

DockOps uses voids as the primary correction mechanism.

Voiding a dock request is different from canceling it:

- Cancel is “we didn’t do it; stop trying.”
- Void is “we did something, but it was wrong; unwind it.”

Voiding a dock request reverses its effects (reservations and on-hand units). That means a void can change hub posture, consignment status, and whether other work is now possible.

Corrections are allowed to be blocked when they would create nonsense:

- A move can’t be voided if later moves would make on-hand units go negative; the API returns `ERR_CONSTRAINT_VIOLATION`.
- If voiding an outbound move would add units back beyond what the hub can hold, it fails as `ERR_CAPACITY_EXCEEDED`.

When a variance-created hold is still `OPEN` and linked to a dock request, voiding that dock request automatically voids the hold as well (it’s treated as “that issue never happened”).

Closed isn’t sacred: if a correction or a new hold creates new activity, the consignment stops being `CLOSED` (clients will see it back in an active status).

## Operations checkpoint (`run_ops`)

Hubs run explicit checkpoints instead of relying on wall-clock time.

Calling `run_ops` increments `ops_run_index` and applies two sweeps:

1. Stale request expiry: a `SUBMITTED` or `ON_HOLD` request that sits through **two** ops runs without becoming scheduled expires into `EXPIRED`.
2. Administrative closeout: a consignment in `RELEASED` with no open holds and no open move becomes `CLOSED`.

## Safety headers and predictable failures

This is the “boring stuff” that keeps hubs from drifting when scanners retry, ops clicks twice, or two clients race to update the same request.

### Response envelope

Responses use an envelope with `response_type` and `data`. The `response_type` is `object` for single-resource responses, `array` for collections, or `error` for failures. Error payloads include `error_code` and a human `message`.

### Versioning (If-Match)

For requests that change an existing resource (`PUT` and state-changing actions), clients also send `If-Match` with the current `etag`. If the `etag` is missing, the API returns `ERR_MISSING_IF_MATCH`. If it doesn’t match, the API returns `ERR_VERSION_CONFLICT`.

### Error precedence (what you’ll see first)

DockOps reports errors in a predictable order:

1. Missing `If-Match` when required (`ERR_MISSING_IF_MATCH`)
2. Unknown IDs / wrong hub scope (`ERR_NOT_FOUND`)
3. Stale `etag` (`ERR_VERSION_CONFLICT`)
4. Hub posture gates (for example `ERR_POSTURE_LOCKDOWN`, `ERR_CONGESTED_INBOUND_LIMIT`)
5. Shipment-level blockers (open holds before empty stock), then other state/constraint failures

## Endpoints

| Method | Path |
|--------|------|
| POST | /hubs |
| GET | /hubs/:hub_id |
| POST | /hubs/:hub_id/consignments |
| GET | /hubs/:hub_id/consignments/:consignment_id |
| POST | /hubs/:hub_id/consignments/:consignment_id/void |
| POST | /hubs/:hub_id/dock_requests |
| GET | /hubs/:hub_id/dock_requests/:dock_request_id |
| PUT | /hubs/:hub_id/dock_requests/:dock_request_id |
| POST | /hubs/:hub_id/dock_requests/:dock_request_id/submit |
| POST | /hubs/:hub_id/dock_requests/batch_schedule |
| POST | /hubs/:hub_id/dock_requests/:dock_request_id/cancel |
| POST | /hubs/:hub_id/dock_requests/:dock_request_id/complete |
| POST | /hubs/:hub_id/dock_requests/:dock_request_id/void |
| POST | /hubs/:hub_id/holds |
| GET | /hubs/:hub_id/holds/:hold_id |
| POST | /hubs/:hub_id/holds/:hold_id/clear |
| POST | /hubs/:hub_id/holds/:hold_id/void |
| POST | /hubs/:hub_id/run_ops |

## Appendix: Error codes

- ERR_BAD_REQUEST
- ERR_NOT_FOUND
- ERR_MISSING_IF_MATCH
- ERR_VERSION_CONFLICT
- ERR_INVALID_STATE
- ERR_POSTURE_LOCKDOWN
- ERR_CONGESTED_INBOUND_LIMIT
- ERR_CAPACITY_EXCEEDED
- ERR_CONSIGNMENT_HAS_OPEN_HOLD
- ERR_CONSIGNMENT_EMPTY
- ERR_CONSIGNMENT_BUSY
- ERR_CONSTRAINT_VIOLATION