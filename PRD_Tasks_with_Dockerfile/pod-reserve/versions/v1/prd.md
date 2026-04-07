# PodReserve: Sponsorship Reservations + Compliance for Podcasts

PodReserve is the backend behind a very specific workflow: podcasts sell **host-read sponsorships** into episodes, and they need a way to reserve inventory without accidentally overselling (or publishing an episode that’s mid-dispute).

Everything is scoped to a single **podcast**. Nothing is shared across podcasts—IDs don’t “work” across podcasts, even if they exist somewhere else.

The product is intentionally small on the outside: clients mostly create episodes, create sponsor deals, reserve placements, and occasionally deal with claims. The tricky part is that the “simple” totals a client reads—how much inventory is left, how much budget is left, whether the podcast is restricted—move in lots of places, including corrections and reclassifications.

## Podcasts: the thing people actually watch

A podcast is where teams track their ad inventory budget. Creating a podcast accepts a `name` and an `ad_capacity_seconds` (the total seconds of host-read inventory the podcast is willing to carry at a time).

Reading a podcast returns its `id`, `name`, and a few derived fields that clients tend to pin on dashboards:

- `posture` is either `NORMAL` or `RESTRICTED`.
- `open_claim_count` is the number of claims in `OPEN` status.
- `ops_run_index` is a simple counter that increments whenever ops runs happen.
- `ad_held_seconds` and `ad_committed_seconds` move as reservations move.
- `ad_available_seconds` is what’s left of the podcast’s capacity after holds and commitments; it never goes negative.

A reservation’s `slot_seconds` counts against the podcast’s inventory while it’s in `HOLD`, and it continues counting once it’s approved or settled. When a reservation is canceled, expired, overbooked, credited, or otherwise no longer expected to run in the feed, those seconds stop counting.

## Episodes: draft, submit, publish… and sometimes pull back

Episodes start life as editorial objects, but they become the “anchor” for sponsorship reservations.

Creating an episode accepts a `title`, a `content_rating` (either `GENERAL` or `MATURE`), and `ad_slots_total_seconds` (how many seconds of host-read inventory the episode is willing to carry). Episodes start in `DRAFT` status and `CLEAR` clearance.

Episodes move through a small lifecycle:

- `DRAFT` → `SUBMITTED` (teams are done editing and want the episode to be eligible to go live)
- `SUBMITTED` → `LIVE` (the episode is published)
- `SUBMITTED` or `LIVE` → `RETRACTED` (the episode is pulled from distribution)

Reading an episode returns the episode’s `status`, its `clearance` (`CLEAR` or `UNDER_REVIEW`), and a small set of inventory fields: `ad_slots_total_seconds`, `ad_slots_held_seconds`, and `ad_slots_committed_seconds`. Clients also see a `reservations` array on the episode (each entry includes the reservation `id`, `deal_id`, `placement`, `slot_seconds`, `status`, `script_version_pinned`, and `version`).

Editing happens through `PUT` and is only available while an episode is still `DRAFT`. Editorial teams change `title`, update `content_rating`, and occasionally tighten `ad_slots_total_seconds` when a cut runs long.

Two “product-y” behaviors show up when an episode’s ad capacity changes:

- Tightening `ad_slots_total_seconds` doesn’t silently violate the math. If the episode can’t fit what it’s already holding/committing, holds get dropped first (newest holds are the first to get canceled), and if that still isn’t enough, the most recently approved reservations are bumped into `OVERBOOKED`.
- `OVERBOOKED` reservations don’t consume episode or podcast capacity, and they don’t consume deal budget while they’re overbooked. They still exist on the episode until they’re canceled or successfully approved again (usually after capacity increases).

Publishing is intentionally conservative. An episode can’t go `LIVE` while any reservation on it is in `HOLD`, `NEEDS_REVIEW`, or `OVERBOOKED`. Publishing is also blocked while the episode is `UNDER_REVIEW`, or while the podcast is `RESTRICTED`.

Retraction is the correction path for episodes. Retraction has two flavors in practice:
- Manual retractions are “careful”: if an episode still has any `HOLD` reservations, `POST …/retract` is blocked with `ERR_EPISODE_HAS_HOLDS` (the expectation is you either cancel those holds, or let ops expire them).
- Compliance takedowns are “immediate”: when a claim is closed as `ACCEPTED`, the platform retracts the episode right away and cleans up holds as part of that correction.

Retraction also unwinds sponsorship side effects across the system:
- `HOLD` reservations are canceled (releasing holds).
- `APPROVED` and `NEEDS_REVIEW` reservations are canceled (releasing commitments).
- `SETTLED` reservations are converted to `CREDITED` (the sponsor doesn’t pay for a retracted read; the budget impact is reversed), and they stop counting toward committed seconds.

## Deals: sponsor agreements with budgets and scripts

Deals represent sponsor agreements and the creative that goes with them. Creating a deal accepts:

- `advertiser_name`
- `brand_tier` (`FAMILY_SAFE` or `STANDARD`)
- `budget_total_cents`
- `slot_price_cents` (v1 is intentionally simple: each reservation under the deal consumes one “slot price”, regardless of `slot_seconds`)
- `script_text` (the current host-read copy)

Deals start in `DRAFT`. Teams usually flip the deal’s `status` to `ACTIVE` once paperwork is done; it can also be set to `PAUSED` or `CLOSED`.

Clients read deals primarily to understand budget posture. The deal exposes:
- `budget_held_cents` (slots held but not approved yet)
- `budget_committed_cents` (approved slots that haven’t been settled yet, including `NEEDS_REVIEW`)
- `budget_spent_cents` (settled slots)
- `budget_available_cents` (what’s left after held + committed + spent)
- `script_version` (starts at 1)

Only `ACTIVE` deals can be used to approve or settle reservations. Deals in `PAUSED` don’t erase history, but they’re treated as “not currently usable” until resumed.

Creative changes are normal. Updating a deal’s `script_text` increments `script_version`, and any reservation that was previously `APPROVED` under that deal becomes `NEEDS_REVIEW`. Those reservations remain committed (they still hold inventory and budget), but they block publishing and settlement until they’re approved again—approving a `NEEDS_REVIEW` reservation pins it to the deal’s current `script_version`.

Brand safety is intentionally blunt in v1:
- `FAMILY_SAFE` deals can’t be approved on `MATURE` episodes. (It’s fine to create holds; approval is where the platform draws the line.)

Closing a deal is a correction mechanism on the sponsor side. When a deal moves to `CLOSED`, the platform cancels any of its reservations that aren’t already terminal (`SETTLED`, `CREDITED`, `CANCELED`, `EXPIRED`). Settled reads remain settled; closing doesn’t retroactively rewrite what already aired unless the episode is retracted (which is when credits happen).

## Reservations: holds, approvals, settlement, and reclassification

Reservations are the atomic “this sponsor has this placement in this episode” object. Creating a reservation accepts an `episode_id`, a `deal_id`, a `placement` (`PRE_ROLL`, `MID_ROLL`, or `POST_ROLL`), and `slot_seconds`.

Reservations start in `HOLD`. Holds are real: they consume podcast inventory (`ad_held_seconds`), episode inventory (`ad_slots_held_seconds`), and deal budget (`budget_held_cents`). This is how the platform avoids overselling when teams “pencil in” multiple sponsors.

Approving a reservation moves it to `APPROVED`. Approval shifts the reservation’s slot from “held” into “committed”:
- The podcast’s `ad_held_seconds` goes down and `ad_committed_seconds` goes up.
- The episode’s `ad_slots_held_seconds` goes down and `ad_slots_committed_seconds` goes up.
- The deal’s `budget_held_cents` goes down and `budget_committed_cents` goes up.
The reservation pins a `script_version_pinned` at approval time.

Reclassification is a first-class behavior:
- When a deal’s script changes (new `script_version`), approved reservations move to `NEEDS_REVIEW`.
- When an episode’s `content_rating` changes, previously approved reservations that now violate brand safety also end up in `NEEDS_REVIEW`.
- When an episode’s ad capacity shrinks, later approvals may be pushed into `OVERBOOKED` (and stop consuming capacity/budget until resolved).

Settlement is how sponsors get charged. Settling moves a reservation from `APPROVED` to `SETTLED`, and the deal moves budget from committed into spent. Settlement is only possible once the episode is `LIVE`.

Cancellations happen in multiple places:
- A client can cancel a reservation in `HOLD`, `APPROVED`, `NEEDS_REVIEW`, or `OVERBOOKED`, which moves it to `CANCELED` and releases whatever it was consuming.
- Holds can also expire automatically (see ops runs below), which moves them to `EXPIRED`.

Terminal reservation statuses in day-to-day life are usually `SETTLED`, `CREDITED`, `CANCELED`, or `EXPIRED`.

## Claims and posture: when “business as usual” isn’t safe

Claims are the compliance hook. Clients file a claim against an episode with a `kind` (`RIGHTS` or `BRAND_SAFETY`). Claims begin `OPEN`, and a podcast counts them toward `open_claim_count`.

An episode with any open claim is `UNDER_REVIEW`. Under review is sticky until all its claims are closed. Under review blocks:
- publishing the episode
- approving reservations on that episode
- settling reservations on that episode

Closing a claim accepts an `outcome`: `ACCEPTED`, `REJECTED`, or `WITHDRAWN`. Closing with `REJECTED` or `WITHDRAWN` simply resolves the dispute. Closing with `ACCEPTED` is treated as a compliance takedown:
- the episode is retracted immediately
- holds are cleaned up as part of that correction
- settled reads become credited

Podcast posture uses claims as the signal:
- If `open_claim_count` reaches two or more, the podcast becomes `RESTRICTED`.
- Also, any `ACCEPTED` claim puts the podcast into `RESTRICTED` posture until ops runs once after all claims are closed.

In `RESTRICTED` posture, the platform blocks new commitments:
- episodes can’t be published
- reservations can’t be approved
- deals can’t be activated (status can’t move to `ACTIVE`)
Work that reduces risk is still allowed: canceling reservations, retracting episodes, closing claims, revising scripts, and running ops.

## Ops runs: predictable housekeeping without clocks

PodReserve avoids wall-clock timing. When the business wants cleanup, ops triggers it explicitly using `POST /podcasts/:podcast_id/run_ops`.

Each run increments `ops_run_index`. Ops runs do two things:

1) Hold expiry: a reservation that remains `HOLD` for two ops runs expires into `EXPIRED` and releases its held inventory and budget.

2) Posture reset after takedown: if the podcast is restricted solely because of a prior accepted claim (and there are no `OPEN` claims remaining), an ops run clears the podcast back to `NORMAL`.

## Request safety: optimistic concurrency

PodReserve gets hit by retries and partial failures constantly (ad ops tools, partner integrations, people double-clicking approvals). The system stays usable by refusing “quiet overwrites.”

Any request that changes an existing resource expects `If-Match` with the resource’s current `version`. Versions are integers, and they increment on each successful state change (including reclassifications like moving a reservation into `NEEDS_REVIEW`).

When multiple problems apply, errors surface in a consistent order:
1) missing required headers (`ERR_MISSING_IF_MATCH`)
2) unknown IDs / wrong podcast (`ERR_NOT_FOUND`)
3) podcast posture blocks (`ERR_PODCAST_RESTRICTED`)
4) invalid lifecycle transitions (`ERR_INVALID_STATE`)
5) other business rule failures (capacity, budget, duplicates, brand safety, review gates)

## Endpoints

| Method | Path |
|---|---|
| POST | /podcasts |
| GET | /podcasts/:podcast_id |
| POST | /podcasts/:podcast_id/run_ops |
| POST | /podcasts/:podcast_id/episodes |
| GET | /podcasts/:podcast_id/episodes/:episode_id |
| PUT | /podcasts/:podcast_id/episodes/:episode_id |
| POST | /podcasts/:podcast_id/episodes/:episode_id/submit |
| POST | /podcasts/:podcast_id/episodes/:episode_id/publish |
| POST | /podcasts/:podcast_id/episodes/:episode_id/retract |
| POST | /podcasts/:podcast_id/deals |
| GET | /podcasts/:podcast_id/deals/:deal_id |
| PUT | /podcasts/:podcast_id/deals/:deal_id |
| POST | /podcasts/:podcast_id/reservations |
| POST | /podcasts/:podcast_id/reservations/:reservation_id/approve |
| POST | /podcasts/:podcast_id/reservations/:reservation_id/cancel |
| POST | /podcasts/:podcast_id/reservations/:reservation_id/settle |
| POST | /podcasts/:podcast_id/claims |
| POST | /podcasts/:podcast_id/claims/:claim_id/close |

## Appendix: response envelope, headers, and errors

All responses use a simple envelope with `response_type` and `data`. Success responses use `response_type="object"` (or `response_type="array"`). Error responses use `response_type="error"` and include `data.error_code` and `data.message`.

Required headers:
- `If-Match` (any endpoint that mutates an existing resource: `PUT` and `POST` actions on existing IDs)

Error codes:
- ERR_BAD_REQUEST
- ERR_NOT_FOUND
- ERR_MISSING_IF_MATCH
- ERR_VERSION_CONFLICT
- ERR_PODCAST_RESTRICTED
- ERR_INVALID_STATE
- ERR_CAPACITY_EXCEEDED (includes `capacity_scope` of `PODCAST` or `EPISODE`)
- ERR_DEAL_BUDGET_EXCEEDED
- ERR_DEAL_NOT_ACTIVE
- ERR_EPISODE_UNDER_REVIEW
- ERR_BRAND_SAFETY_MISMATCH
- ERR_DUPLICATE_RESERVATION
- ERR_DUPLICATE_CLAIM
- ERR_EPISODE_HAS_HOLDS
- ERR_EPISODE_HAS_UNREVIEWED_RESERVATIONS
- ERR_EPISODE_HAS_OVERBOOKED_RESERVATIONS