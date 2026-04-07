# SponsorshipOps API

This service is for event ops teams who sell sponsorship packages (Gold, Silver, etc.) and then have to *actually* deliver the benefits (logo placements, lead scans, stage time) without overselling or losing track of what was promised.

Everything here is scoped to a single `event`. No cross-event lookups, no “global sponsor record.” If you have two events, they’re two separate worlds.

A lot of this product is intentionally boring on the surface: create packages, let sponsors apply, approve, then track benefit usage. The part that matters is that the “inventory picture” stays honest even after corrections, pauses, and compliance changes.


## Events

An `event` is the unit this service operates on. Creating one accepts a `name` and a `spotlight_slot_count` (how many sponsors can be featured in the “Spotlight” placement for this event). An event starts in `DRAFT` posture.

Reading an event is also where clients check a couple of “north star” outcomes:
- `posture` tells you whether sponsor-facing workflow is currently running.
- `ops_run_index` is a counter that bumps each time ops runs the checkpoint job.
- `spotlight_slots_remaining` reflects how many spotlight placements are still available right now (based on finalized Spotlight claims).
- `version` increments whenever the event changes.

Event posture is one of: `DRAFT`, `OPEN`, `LOCKDOWN`, `ARCHIVED`.


The intended vibe:
- `DRAFT` is for setup: building the sponsorship catalog, adding sponsors, letting sponsors draft applications.
- `OPEN` is normal operations.
- `LOCKDOWN` is “pause the event” (often because something compliance-ish is happening). During lockdown, sponsor-facing progress stops, but ops can still do cleanup.
- `ARCHIVED` is “we’re done selling and fulfilling,” but paperwork-style corrections can still happen.

In practice:
- You can move forward into `OPEN`, and you can pause/resume using `LOCKDOWN`. But you can't rewind an event back into `DRAFT`, and you can't "un-archive" an event once it's `ARCHIVED`. Those attempts fail with `ERR_INVALID_STATE`.
- During `LOCKDOWN`, **these are blocked**: creating new resources (packages, applications, claims), and any “forward progress” transitions like approving an application, countersigning a commitment, or finalizing a claim.
- During `LOCKDOWN`, **these still work**: withdrawals, voids, rescinds, sponsor risk updates, and `run_ops`.
- During `ARCHIVED`, it’s the same idea as lockdown: no new business, but corrections are still allowed.


## Packages (what’s for sale)

A `package` is something like “GOLD” or “SILVER.” Creating a package usually includes:
- a `label`
- a `price_cents`
- a `slot_count` (how many sponsors can buy it)
- an `included_benefits` list (each entry has a `benefit_kind` and `quantity`)

Benefit kinds used in v1:
- `LEAD_SCANS`
- `STAGE_MINUTES`
- `SPOTLIGHT`

Packages have `status` (`ACTIVE` or `RETIRED`). Retiring a package means “stop offering it.” Existing commitments don’t disappear, but new demand shouldn’t keep accumulating.

Clients read `slots_remaining` on the package to understand availability. This number stays accurate even when holds expire, waitlists move, commitments get rescinded, or sponsors get blocked.

Retiring a package has a very visible side effect: any currently held slot reservations for that package are released, and those submissions fall back to the waitlist (they keep their place in line). The waitlist itself doesn’t vanish; it just stops advancing while the package is retired.


## Sponsors (trust posture)

A `sponsor` is a company participating in a single event. Creating a sponsor accepts things like `display_name`, `legal_name`, and `primary_contact_email`.

Sponsors carry a `status`:
- `PROSPECT`
- `VETTED`
- `WATCHLIST`
- `BLOCKED`

By default, a newly created sponsor starts as `PROSPECT`. Ops can later move them into `VETTED`, `WATCHLIST`, or `BLOCKED` as risk posture changes.

This status is not just a label; it changes what the system does:
- A sponsor in `BLOCKED` can’t progress anything new (applications, approvals, claims). Blocking is an operational “big hammer,” and it triggers cleanup cascades.
- Moving a sponsor to `WATCHLIST` pauses delivery on their active sponsorships: active commitments become suspended until ops explicitly countersigns them again.
- Moving a sponsor to `VETTED` mostly affects the future (new approvals can go straight to active), but it doesn’t magically undo prior suspensions or rescinds.

Blocking is a special case. When a sponsor becomes `BLOCKED`, the system revokes their participation in a very concrete way:
- Any non-terminal applications are withdrawn (and removed from the waitlist / hold picture).
- Any non-rescinded commitments are rescinded.
- Any benefit claims under those commitments are voided (including already-finalized claims).
This is one of the ways the system “unwinds” previously granted inventory and benefits.


## Applications (requesting a package)

Sponsors apply to a package through an `application`. Applications are meant to be drafted and then submitted. Applications can carry a `note` field for free-form comments.

Application `status` values:
- `DRAFT`
- `SUBMITTED`
- `APPROVED`
- `REJECTED`
- `WITHDRAWN`
- `EXPIRED`

Draft behavior is straightforward: a draft can be edited (it has a `version`, and its `note` can be updated), and it can be withdrawn.

Submission is where the inventory logic kicks in:
- Submitting assigns a monotonically increasing `submit_seq` (used for ordering within a package).
- Submitted applications have a `hold_status`, either `HELD` or `WAITLISTED`.
- If the submission is `HELD`, it has a `hold_expires_on_ops` value (an ops-run index). The hold expires when ops runs enough times.
- If the submission is `WAITLISTED`, it doesn’t expire automatically; it’s simply waiting for a slot to become available.

There are two key rules that make the waitlist feel sane:
1) **No line-cutting.** Once a package has a waitlist, newly submitted applications join the waitlist even if a slot is technically free at that moment.
2) The waitlist only advances during `run_ops`. Slots can free up anytime (withdrawals, rescinds, expiry), but holds are granted in a batch during the checkpoint.

Applications are intentionally “one-at-a-time” per sponsor/package. A sponsor can’t have two concurrent applications for the same package in non-terminal states.


## Approvals create Commitments (the thing that actually reserves inventory)

Approving an application produces a `commitment`. This is the durable record that “this sponsor owns a slot in this package.” The application also records which commitment got created (`commitment_id`), so clients can follow the thread from “what was approved” to “what’s active.”

A commitment has a `status`:
- `PENDING_COUNTERSIGN` (needs ops to countersign before it’s active)
- `ACTIVE`
- `SUSPENDED` (paused due to sponsor risk)
- `RESCINDED`

Approving an application requires that it's `SUBMITTED` **and** currently `HELD`. You can reject or withdraw from the waitlist, but you can't approve from the waitlist.

Commitments are what permanently consume a package slot. Holds are temporary; commitments are the thing the inventory math really cares about.

When a commitment is not active (`PENDING_COUNTERSIGN` or `SUSPENDED`), it also carries an `activation_deadline_on_ops`. If that deadline arrives and the commitment still isn’t active, ops considers it abandoned and revokes it automatically during `run_ops`. That automatic revocation is not gentle: it rescinds the commitment and voids any claims tied to it.


## Claims (using the benefits)

A commitment has a `benefits_left` summary—a map from `benefit_kind` to remaining quantity—derived from the package's `included_benefits` minus any finalized claims. For example, `{"LEAD_SCANS": 75, "STAGE_MINUTES": 30, "SPOTLIGHT": 1}`.

Sponsors “use” benefits by creating `claims` under the commitment. Claims have:
- `benefit_kind`
- `quantity`
- `status` (`PROPOSED`, `FINALIZED`, `VOIDED`)

Creating a claim records intent (`PROPOSED`). Finalizing a claim is what consumes inventory:
- It decrements `benefits_left` for that kind.
- For `SPOTLIGHT`, it also consumes from the event’s `spotlight_slot_count` global pool (which is why events expose `spotlight_slots_remaining`).

The Spotlight rules are intentionally strict:
- `SPOTLIGHT` claims always have `quantity` of 1.
- A commitment can’t have multiple non-voided Spotlight claims at the same time (even multiple proposals).
- Finalizing a Spotlight claim fails when the event is out of spotlight slots.

Voiding is the correction path:
- Voiding a `FINALIZED` claim restores `benefits_left` and (for Spotlight) releases a spotlight slot back to the event.
- Voiding a `PROPOSED` claim just marks it voided (no inventory to restore).

Commitment reads include a small `claims` list so clients can see what has been proposed/finalized/voided without fetching claims separately.


## Corrections and cleanup

This product assumes mistakes happen and policy changes happen.

The primary corrections are:
- withdrawing an application (`WITHDRAW`)
- rescinding a commitment (`RESCIND`)
- voiding a claim (`VOID`)
- blocking a sponsor (cascades withdraw + rescind + void)

Rescinding a commitment in normal operations is “polite”: if there are finalized claims, the API surfaces that and expects the operator to void the claims first. (That’s how ops intentionally unwinds delivered benefits.)

Revocations triggered by policy (`BLOCKED`) or abandonment (`activation_deadline_on_ops` reached during `run_ops`) are “not polite”: they rescind and void as part of the same cleanup, so inventory and spotlight slots aren’t left stuck.


## The ops checkpoint: `run_ops`

`POST /events/:event_id/run_ops` is the explicit checkpoint. It bumps `ops_run_index` by 1 and then applies housekeeping in a predictable order:

1) Expire holds: any `SUBMITTED` application that is `HELD` and whose `hold_expires_on_ops` has arrived becomes `EXPIRED` and releases its slot.
2) Revoke abandoned commitments: any non-active commitment whose `activation_deadline_on_ops` has arrived becomes `RESCINDED`, and its claims are voided.
3) Advance waitlists: for each `ACTIVE` package, newly freed slots are granted as holds to the oldest waitlisted submissions (lowest `submit_seq`).

A practical way to think about it: `run_ops` is the moment when the system reconciles “what’s true” across inventory, waitlists, expiries, and corrections.


## Replay safety and safe updates

This system gets hammered by retries and racey admin tooling. It stays predictable by being strict about stale writes.

- `If-Match`: any `PATCH` or `PUT` expects `If-Match` set to the resource’s current `version`. Stale versions return `ERR_VERSION_CONFLICT`. Missing `If-Match` returns `ERR_PRECONDITION_REQUIRED`.

Versions bump on every change, including state transitions and cascades caused by `run_ops` or sponsor status changes.


## Response envelope

Responses are wrapped in a common envelope. Success responses have `response_type` set to `"object"` for single resources or `"array"` for lists, with `data` holding the payload. Errors return `response_type="error"` with `data.error_code` and a human `message`.


## Error precedence

A small global precedence keeps collisions predictable for callers:
1) Missing required headers (`ERR_PRECONDITION_REQUIRED`)
2) Unknown IDs (`ERR_NOT_FOUND`)
3) Version conflicts (`ERR_VERSION_CONFLICT`)
4) Posture blocks (`ERR_EVENT_NOT_OPEN`, `ERR_EVENT_LOCKDOWN`)
5) State machine blocks (`ERR_INVALID_STATE`)
6) Domain rules and capacity (`ERR_*`)


## Endpoints

POST /events  
GET /events/:event_id  
PATCH /events/:event_id  
POST /events/:event_id/run_ops  

POST /events/:event_id/packages  
GET /events/:event_id/packages/:package_id  
POST /events/:event_id/packages/:package_id/transition  

POST /events/:event_id/sponsors  
GET /events/:event_id/sponsors/:sponsor_id  
PATCH /events/:event_id/sponsors/:sponsor_id  

POST /events/:event_id/applications  
GET /events/:event_id/applications/:application_id  
PUT /events/:event_id/applications/:application_id  
POST /events/:event_id/applications/:application_id/transition  

GET /events/:event_id/commitments/:commitment_id  
POST /events/:event_id/commitments/:commitment_id/transition  

POST /events/:event_id/commitments/:commitment_id/claims  
POST /events/:event_id/commitments/:commitment_id/claims/:claim_id/transition  


## Appendix: tokens

Required headers:
- If-Match (required on PUT/PATCH)

Transition actions:
- application.transition `action`: `SUBMIT`, `APPROVE`, `REJECT`, `WITHDRAW`
- package.transition `action`: `RETIRE`, `REACTIVATE`
- commitment.transition `action`: `COUNTERSIGN`, `RESCIND`
- claim.transition `action`: `FINALIZE`, `VOID`

Error codes:
- ERR_BAD_REQUEST
- ERR_NOT_FOUND
- ERR_PRECONDITION_REQUIRED
- ERR_VERSION_CONFLICT
- ERR_EVENT_NOT_OPEN
- ERR_EVENT_LOCKDOWN
- ERR_INVALID_STATE
- ERR_PACKAGE_RETIRED
- ERR_DUPLICATE_APPLICATION
- ERR_DUPLICATE_COMMITMENT
- ERR_NO_ACTIVE_HOLD
- ERR_SPONSOR_BLOCKED
- ERR_COMMITMENT_NOT_ACTIVE
- ERR_BENEFIT_NOT_INCLUDED
- ERR_INSUFFICIENT_BENEFIT
- ERR_DUPLICATE_CLAIM
- ERR_SPOTLIGHT_FULL
- ERR_SPOTLIGHT_IN_USE
- ERR_HAS_FINALIZED_CLAIMS