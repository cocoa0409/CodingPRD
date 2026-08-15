# Cinema Advertising & Pre-Show Programming API — Product Requirements Document

## 1. Introduction

A national cinema advertising network sells the minutes before the feature begins. Its inventory is finite and perishable: every auditorium's pre-show timeline holds a fixed pool of seconds, split between national brand campaigns and local merchant spots, and every second must be sold, assembled into a reel, delivered to the right theater, verifiably played in front of a real audience, and then billed against the attendance that actually showed up. This document specifies the API through which the network runs that entire business — from registering screens and forecasting their audiences, through reserving slots under exclusivity and content-rating rules, to playback verification, attendance audit, impression-based invoicing, and make-good credits when a flight under-delivers.

The system serves four constituencies with deliberately segregated duties: network operations staff who program the inventory and move reels through delivery, sales managers who book campaigns and bill them, theater-side operators who acknowledge deliveries and report what played and who watched, and independent auditors who certify the numbers that money moves on. All endpoints are mounted under the `/network` prefix. Because several workflows involve multiple writers touching the same aggregate, the API applies explicit optimistic concurrency controls, and because the business is time-driven, the platform runs on a controllable logical clock rather than wall-clock time.

## 2. Global Specifications & System-Wide Principles

This section defines the structural contracts and system-wide rules that hold for every endpoint.

### 2.1. User and Role-Based Access Control

Every request must carry two context headers: `X-User-ID`, identifying the acting operator, and `X-User-Role`, declaring the capacity in which they act. Four roles exist, spelled exactly as follows: `NetworkOps`, `SalesManager`, `TheaterOps`, and `Auditor`. A request missing either header, or presenting a role outside that set, is rejected with `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` (HTTP 400). A request whose role is valid but not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403); the per-endpoint authorization matrix appears in §4.

`TheaterOps` is the only entity-backed role. When `X-User-Role` is `TheaterOps`, `X-User-ID` is the `id` of the acting `Theater`; ownership checks on any resource reached through a showtime's screen compare the owning theater's `id` against `X-User-ID`. This theater scope governs exactly four operations — acknowledging a reel's delivery, recording a playback log for a slot, submitting an attendance report for a showtime, and resubmitting a disputed attendance report — and a caller whose `X-User-ID` does not equal the `id` of the theater that owns the target showtime's screen is rejected with `ERR_THEATER_SCOPE_MISMATCH` (HTTP 403).

When `X-User-Role` is `NetworkOps`, `SalesManager`, or `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it on resources where a workflow writes it — for example `created_by_user_id` on a campaign, `reviewed_by_user_id` on an attendance report, or `certified_by_user_id` on an invoice — but it is never compared to any entity's `id` for ownership; it feeds only the segregation-of-duties comparisons of §2.7.

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, and any value from a minimum of 1 to a maximum of 100 is accepted. The `offset` parameter states how many items to skip and defaults to 0. A `limit` outside the 1–100 range, a negative `offset`, or a non-integer value for either parameter is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. The `meta` object of a list response carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`; `has_more` is true exactly when `offset` plus the number of items returned is less than `total_count`.

### 2.4. Common Resource Properties

Every persisted resource carries a system-minted `id` formatted as a UUID with no type prefix, together with a `created_at` timestamp in ISO 8601 UTC form with three fractional digits. Every resource except the PlayLog additionally carries `updated_at` — an ISO 8601 UTC timestamp with three fractional digits, refreshed on any change to the resource — and `version`, a system-managed integer that increments by one on every mutation of the resource, including mutations applied as a side effect of an operation on some other resource. The PlayLog is an append-only verification record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it. A freshly created reel begins at `version` 1, and each subsequent mutation of that reel — reserving a slot, canceling one, locking the assembly — increments it by one.

### 2.5. The Logical Clock

Time inside the platform is a controllable logical clock, not the wall clock. Before any operator sets it, the clock's startup default is exactly `2026-08-01T00:00:00Z`, and the server never falls back to wall-clock time. A `NetworkOps`-only test-driving capability sets the clock to a supplied `to_iso8601` instant and answers with the resulting `current_utc`; the supplied string is retained verbatim, so `current_utc` echoes it exactly as supplied, and the same verbatim string is what is later stamped onto each PlayLog's `played_at`. The logical clock governs the delivery deadline for a reel (§3.4), the earliest moment a playback record may be filed (§3.4), and the `played_at` stamp written onto each PlayLog.

### 2.6. Request Validation Pipeline and Nested Resource Retrieval

When several checks could fail on the same request, the server evaluates them in a fixed priority order, so the error a caller receives is deterministic:

1. **Context headers** — presence of `X-User-ID` and `X-User-Role` and membership of the role in the declared set, failing as `ERR_MISSING_OR_INVALID_CONTEXT_HEADER`.
2. **Role authorization** — whether the caller's role is permitted on this endpoint, failing as `ERR_FORBIDDEN_ROLE`.
3. **Theater scope** — for `TheaterOps` callers, whether `X-User-ID` equals the `id` of the theater owning the target showtime's screen, failing as `ERR_THEATER_SCOPE_MISMATCH`. Evaluating this scope requires resolving the target resource, so a path identifier that does not resolve answers `ERR_NOT_FOUND` before any scope comparison can be made.
4. **Request shape** — required fields present, types valid, enum values in-domain, date fields in ISO form, datetime fields carrying an explicit timezone designator (`Z` or an offset), `period_end_date` not earlier than `period_start_date`, and `flight_end_date` not earlier than `flight_start_date`, failing as `ERR_INVALID_REQUEST`.
5. **Existence** — every referenced resource must exist, failing as `ERR_NOT_FOUND`. Path identifiers are validated left-to-right, so the first missing id in the path determines the error; only after the path resolves are body-referenced foreign keys such as `campaign_id` and `feature_id` checked.
6. **Segregation of duties** — the four pairwise identity comparisons of §2.7.
7. **State preconditions** — the guards of §3, failing with the state-tier errors listed in §5. Within a single request, the state of the resource named in the URL path is checked before the state of resources referenced in the body: on slot reservation, the reel's assembly state is examined before the campaign's approval state. Wherever §3 defines a transition without naming a specific error for attempting it from a state outside its defined source set, the rejection is `ERR_INVALID_STATE_TRANSITION` (HTTP 409).
8. **Rating-based placement** — the advertiser-category versus content-rating rule of §3.3, failing as `ERR_RATING_PLACEMENT_VIOLATION`.
9. **Constraint tier** — for slot creation, evaluated in this order: category exclusivity, then interval overlap, then pool capacity. The sibling checks on other creation endpoints — the screen's buffered-overlap rule on showtime scheduling, the duplicate-open-report rule on attendance submission, and the period-overlap rule on invoice creation — live in this same tier.
10. **Temporal tier** — the flight-window rule on slot creation, the delivery deadline on delivery acknowledgment, and the no-earlier-than-showtime rule on playback recording.
11. **Fiscal tier, always last** — the campaign budget cap on slot creation, failing as `ERR_BUDGET_EXCEEDED`.

This pipeline also governs nested retrieval: any endpoint whose path contains more than one identifier validates them sequentially from left to right and answers `ERR_NOT_FOUND` for the first identifier that does not resolve, never reaching the checks that follow. A request that matches no route, or whose method the matched route does not support, is answered in the standard error envelope with `error_id` `ERR_NOT_FOUND` and the HTTP status of the routing failure.

### 2.7. Segregation of Duties

No operator may confirm their own work. Four pairwise rules are enforced, each rejected with its own HTTP 403 error:

- Campaign approval and campaign rejection both require the caller's `X-User-ID` to differ from the campaign's `created_by_user_id`; an overlap is rejected with `ERR_SOD_APPROVER_IS_CREATOR`.
- Invoice certification requires the certifying `Auditor` to differ from the invoice's `issued_by_user_id`; an overlap is rejected with `ERR_SOD_CERTIFIER_IS_ISSUER`.
- Attendance audit requires the auditing `Auditor` to differ from the report's `reported_by_user_id`; an overlap is rejected with `ERR_SOD_AUDITOR_IS_REPORTER`.
- Make-good review requires the reviewing `Auditor` to differ from the credit's `proposed_by_user_id`; an overlap is rejected with `ERR_SOD_REVIEWER_IS_PROPOSER`.

### 2.8. Optimistic Concurrency Control

Three write operations guard against stale reads through optimistic concurrency control. Each requires a non-optional expected-version field naming the parent aggregate whose `version` the client last observed, and a mismatch with the parent's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412):

- Reserving a slot — `POST /network/reels/{reel_id}/slots` — requires `expected_reel_version` matching the reel's current `version`. If another writer has advanced the reel's version since the client last read it — by adding a slot, canceling one, or locking the assembly — the reservation is rejected rather than built on a stale view of the reel's capacity and offsets.
- Locking a reel — `POST /network/reels/{reel_id}/lock` — requires `expected_reel_version` on the same terms, so a client never locks an assembly that no longer matches what it reviewed.
- Applying a make-good — `POST /network/make-goods/{make_good_id}/apply` — requires `expected_invoice_version` matching the invoice's current `version`, so a credit is never posted against a `final_amount_cents` the caller has not observed.

Within the pipeline of §2.6 the expected-version comparison is evaluated after existence resolution, at an operation-specific point relative to the state tier: on slot reservation it follows the state preconditions (reel `ASSEMBLING`, then campaign `APPROVED`) and precedes rating placement; on reel locking it precedes the lockability precondition; on make-good application it is evaluated first, before the credit-state and invoice-state checks. No other endpoint accepts an expected-version field.

### 2.9. Money, Impressions, and Rounding Discipline

All monetary quantities are integer cents: `cpm_cents`, `budget_cents`, `estimated_cost_cents`, `provisional_amount_cents`, `audited_amount_cents`, `applied_credit_cents`, `final_amount_cents`, and `credit_cents` are whole-cent integers, and wherever a rate multiplication produces a fraction of a cent the value is rounded half-up to the nearest whole cent. Invoice amounts observe a pinned rounding order: each covered slot's line amount is rounded half-up first and the rounded line amounts are then summed — the system never sums unrounded lines and rounds once at the end. Attendance and impression figures — `forecast_attendance`, `actual_attendance`, `attributed_impressions`, `delivered_impressions`, `provisional_impressions`, `audited_impressions`, and `shortfall_impressions` — are integers produced by flooring, applied only after every multiplication in the formula has completed. The make-good eligibility ratio `under_delivery_pct` is compared in exact rational arithmetic, so a ratio of exactly five hundredths remains distinguishable from one strictly greater.

### 2.10. Immediate Consistency and Cross-Aggregate Cascades

Every mutation takes effect immediately: a state change and every cascade it triggers are visible in the same request's response. Cascades freely cross aggregate boundaries — recording playback or accepting an attendance figure rewrites slot attributions and campaign delivery counters, and reserving or canceling a slot rewrites both the reel's pool usage and the campaign's reserved spend. Each mutation of a resource refreshes its `updated_at` and increments its `version`, whether the change arrived through the client's own request or as the side effect of another aggregate's transition. This is precisely what the expected-version fields of §2.8 observe: operations that add, cancel, or lock slots move the reel's `version`, and applying a credit moves the invoice's `version`.

## 3. Business Logic & Workflows

### 3.1. Programming Foundation: Theaters, Screens, Features, and Showtimes

Before a single second of advertising can be sold, `NetworkOps` builds the network's inventory. A theater is registered with a display `name` and a `market_tier` — `MAJOR_METRO`, `REGIONAL`, or `SMALL_MARKET` — that will later drive its attendance forecasts. Every theater begins with `theater_status` `ACTIVE`, and the status enumeration also admits `DARK`. Within a theater, each auditorium is added as a screen carrying an `auditorium_label` such as "Auditorium 7" and a `seat_count` that must be greater than zero. A screen's `theater_id` fixes its ownership for the theater-scope checks of §2.1, and it starts life with `screen_status` `ONLINE` — an enumeration that also admits `OFFLINE`.

Films enter the catalog as features, each registered with a `title`, a `content_rating` of `G`, `PG`, `PG13`, `R`, or `NC17`, a `runtime_minutes` greater than zero, and a `release_date` as an ISO `YYYY-MM-DD` date. Rating and release date are not mere metadata: the rating feeds both the demand factor in the attendance forecast and the placement restrictions of §3.3, while the release date opens the feature's opening-week window, the span from `release_date` through the date seven days after it, both endpoints inclusive.

Programming a showtime on a screen takes a `feature_id` and a `starts_at` UTC instant, with the auditorium fixed by the `screen_id` in the path; `starts_at` is rendered back as the equivalent UTC instant in ISO 8601 form, carrying fractional seconds only when the supplied value had sub-second precision. Scheduling is guarded by the screen's buffered-overlap rule. A new showtime conflicts with an existing one on the same screen when the new start falls before the existing showtime's end — the existing start plus its feature's `runtime_minutes` — plus a thirty-minute turnaround buffer, and at the same time the existing showtime's start falls before the new showtime's end plus the same thirty-minute buffer. A violation is rejected with `ERR_SHOWTIME_OVERLAP`. A gap of exactly thirty minutes between one showtime's end and the other's start is permitted. The showtime listing accepts the optional query filters `screen_id` and `feature_id`.

At creation the showtime snapshots two derived values, and they never change afterward. Its `daypart` is `MATINEE` when the UTC hour component of `starts_at` is less than 17, and `EVENING` otherwise. Its `forecast_attendance` is then computed once: the screen's `seat_count` is multiplied by the occupancy constant for its theater's `market_tier` — 0.40 for `MAJOR_METRO`, 0.32 for `REGIONAL`, and 0.25 for `SMALL_MARKET` — and the resulting base is multiplied by the daypart factor (0.80 for `MATINEE`, 1.20 for `EVENING`), by the rating-demand factor for the feature's `content_rating` (0.90 for `G`, 1.00 for `PG`, 1.10 for `PG13`, 1.05 for `R`, and 0.70 for `NC17`), and finally by the opening-week multiplier, which is 1.25 when the showtime's calendar date falls within the opening-week window described above and 1.0 outside it. The forecast is the floor of that full product, taken only after every multiplication has been applied.

Every showtime is born with exactly one pre-show reel, created automatically alongside it. The reel's `showtime_id` ties it permanently to that showtime; its `reel_status` opens at `ASSEMBLING`; and its timeline holds a `capacity_seconds` of 1200 — a twenty-minute pre-show — split into a `national_pool_seconds` of 720 reservable by `NATIONAL` advertisers and a `local_pool_seconds` of 480 reservable by `LOCAL` ones, with `national_used_seconds` and `local_used_seconds` both starting at zero and the reel's `version` starting at 1. Because the two pools sum exactly to the total capacity, the per-pool capacity check of §3.3 is always the binding constraint, and there is no separate total-capacity error. Retrieving a showtime's reel returns an array containing zero or one element. The showtime's `actual_attendance` stays null until an attendance report is accepted or audited, as §3.5 describes.

### 3.2. Selling the Screen: Advertisers and the Campaign Lifecycle

Demand is onboarded by a `SalesManager`. Each advertiser is created with a `name`, an `advertiser_type` of `NATIONAL` or `LOCAL` — which selects which reel pool its slots draw from — and a `category` of `AUTOMOTIVE`, `QSR`, `RETAIL`, `ENTERTAINMENT`, `TECH`, `ALCOHOL`, or `POLITICAL`, which drives both category exclusivity and rating-based placement. Advertisers are created with `advertiser_status` `ACTIVE`; the enumeration also admits `SUSPENDED`, and a suspended advertiser's campaigns cannot be approved.

A campaign is opened in `DRAFT` against an `advertiser_id`, with a `name`, a flight window given by `flight_start_date` and `flight_end_date` where the end must not precede the start, a `contracted_impressions` total greater than zero that anchors make-good measurement, a `cpm_cents` rate greater than zero expressed in cents per thousand impressions, a `budget_cents` cap greater than zero on reserved estimated spend, and an optional `partial_credit_mode` of `STRICT` or `LENIENT` that defaults to `STRICT`. The server records the creator's header identity in `created_by_user_id` and leaves `approved_by_user_id` null. Both computed counters, `reserved_estimated_cents` and `delivered_impressions`, begin at zero. An advertiser's campaigns can be listed, and an individual campaign read back, by any role.

From `DRAFT`, submission moves the campaign `DRAFT → SUBMITTED`. Review then requires a second `SalesManager`: approval and rejection alike are forbidden to the campaign's creator, and an attempt by the creator is rejected with `ERR_SOD_APPROVER_IS_CREATOR`. Approval moves `SUBMITTED → APPROVED` and stamps `approved_by_user_id`; it additionally requires the advertiser's `advertiser_status` to be `ACTIVE`, and approval of a suspended advertiser's campaign is refused with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Rejection moves `SUBMITTED → REJECTED` and may carry an optional `reason`, which is accepted but not persisted anywhere on the campaign. Editing is permitted only while the campaign is `DRAFT` or `REJECTED`: any subset of `name`, `flight_start_date`, `flight_end_date`, `contracted_impressions`, `cpm_cents`, `budget_cents`, and `partial_credit_mode` may be changed, with the flight-window ordering rule applied to the merged window — each supplied date combined with the stored counterpart, evaluated once the campaign has resolved and before the editable-state guard — and applying an edit to a `REJECTED` campaign reopens it to `DRAFT` and increments the campaign's `version` by one, closing the revise-and-resubmit loop. An edit counts as a mutation even when it supplies no fields at all: it still refreshes `updated_at`, increments `version` by one, and reopens a `REJECTED` campaign to `DRAFT`. A campaign's `campaign_status` is therefore cyclic across `DRAFT`, `SUBMITTED`, and `REJECTED` until it reaches a terminal state.

Cancellation is defined from `DRAFT`, `SUBMITTED`, and `APPROVED`, and is guarded by the campaign's live commitments: if any of its slots is still `RESERVED` or `CONFIRMED`, cancellation is rejected with `ERR_CAMPAIGN_HAS_ACTIVE_SLOTS`. Completion moves `APPROVED → COMPLETED` once the flight has fully played out — every slot of the campaign in `PLAYED`, `MISSED`, or `CANCELED`, again enforced as `ERR_CAMPAIGN_HAS_ACTIVE_SLOTS` — and only while the campaign carries no invoice in `DRAFT` or `ISSUED`, enforced as `ERR_CAMPAIGN_HAS_OPEN_INVOICES`. Both `COMPLETED` and `CANCELED` are terminal.

Two counters track the campaign's commercial health in real time. `reserved_estimated_cents` is the sum of `estimated_cost_cents` over the campaign's slots currently in `RESERVED` or `CONFIRMED`: it grows as slots are reserved, releases a slot's cost when the slot is canceled, keeps counting a slot once its reel locks, and stops counting it only when the slot reaches playback. `delivered_impressions` is the sum of `attributed_impressions` over the campaign's `PLAYED` slots, with slots whose attribution is still null contributing zero; it is recomputed immediately whenever a playback outcome lands and whenever an attendance figure is accepted or revised.

### 3.3. Assembling the Reel: Slot Reservation Under Placement and Capacity Rules

While a reel is `ASSEMBLING`, a `SalesManager` reserves slots inside it. The reservation payload names the `campaign_id`, a `start_offset_seconds` at or after zero marking the creative's start on the reel timeline, and a `duration_seconds` greater than zero; the containing reel is fixed by the `reel_id` in the path. Once the envelope pipeline of §2.6 has passed, the state tier examines the path-named reel first — a reel that has left `ASSEMBLING` rejects the reservation with `ERR_REEL_NOT_ASSEMBLING` — and only then is the body-referenced campaign examined, with any `campaign_status` other than `APPROVED` rejected as `ERR_CAMPAIGN_NOT_BOOKABLE`. Because reservation mutates the assembly, the request must also carry `expected_reel_version` equal to the reel's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412) under the rule of §2.8.

Rating-based placement restricts which creative may sit in front of which film. An `ALCOHOL` advertiser's slot is permitted only on showtimes whose feature's `content_rating` is `R` or `NC17`. A `POLITICAL` advertiser's slot is permitted only on `PG13`, `R`, or `NC17`. The remaining categories are unrestricted. A placement that violates these rules is rejected with `ERR_RATING_PLACEMENT_VIOLATION` (HTTP 422).

Three structural constraints are then evaluated in a fixed order. First, category exclusivity: among the reel's non-`CANCELED` slots, those belonging to the new slot's own campaign are exempt from the comparison, and no slot of any other campaign may belong to an advertiser that shares the new slot's `category`, or the reservation fails with `ERR_CATEGORY_EXCLUSIVITY_CONFLICT`. Second, interval overlap: the new slot occupies the half-open interval from `start_offset_seconds` up to but not including `start_offset_seconds` plus `duration_seconds`, and if that interval intersects any other non-`CANCELED` slot's interval in the reel the reservation fails with `ERR_SLOT_INTERVAL_OVERLAP`; two slots that merely touch endpoints do not conflict. Third, pool capacity: the slot's `duration_seconds` is added to `national_used_seconds` when the campaign's advertiser is `NATIONAL`, or to `local_used_seconds` when it is `LOCAL`, and if the resulting total strictly exceeds the corresponding pool — `national_pool_seconds` of 720 or `local_pool_seconds` of 480 — the reservation is rejected with `ERR_POOL_CAPACITY_EXCEEDED` (HTTP 422); a total exactly equal to the pool's capacity is allowed.

Temporal fitness comes next: the calendar date of the slot's showtime must fall within the campaign's flight window, from `flight_start_date` through `flight_end_date` inclusive, or the reservation is rejected with `ERR_OUTSIDE_FLIGHT_WINDOW` (HTTP 422). The fiscal check is always last. At reservation time the slot snapshots its `estimated_cost_cents` — the showtime's `forecast_attendance` multiplied by the campaign's `cpm_cents`, divided by 1000, and rounded half-up to a whole cent — and if adding that estimate to the campaign's current `reserved_estimated_cents` would exceed the campaign's `budget_cents`, the reservation fails with `ERR_BUDGET_EXCEEDED` (HTTP 422). A reservation that passes every tier lands with `slot_status` `RESERVED`: the estimate is added into the campaign's `reserved_estimated_cents`, the used seconds of the relevant pool increase by `duration_seconds`, and the reel's `version` increments by one.

A `RESERVED` slot can be withdrawn, but only while its reel is still `ASSEMBLING` — locked slots cannot be canceled, and an attempt against a reel past that point is rejected with `ERR_REEL_NOT_ASSEMBLING`. The reel's state is examined before the slot's own, and canceling a slot that is not `RESERVED` while its reel is still `ASSEMBLING` is rejected with `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Cancellation moves the slot `RESERVED → CANCELED`, releases its `duration_seconds` back to whichever pool it drew from, subtracts its `estimated_cost_cents` from the campaign's `reserved_estimated_cents`, and increments the reel's `version` by one. Slots can be read back individually, listed with the optional query filters `reel_id` and `campaign_id`, and a reel's full composition retrieved through the reel itself.

### 3.4. From Lock to Lights-Down: Reel Delivery and Playback Verification

When the assembly is final, `NetworkOps` locks it. Locking requires `expected_reel_version` matching the reel's current `version` under §2.8, and it requires at least one slot still in `RESERVED`; locking a reel that has left `ASSEMBLING`, or one holding zero `RESERVED` slots, is rejected with `ERR_REEL_NOT_LOCKABLE`. A successful lock moves the reel `ASSEMBLING → LOCKED`, transitions every `RESERVED` slot to `CONFIRMED` in the same request, and increments the reel's `version` by one.

A `LOCKED` reel is then dispatched to its theater, moving `LOCKED → IN_TRANSIT`. The theater acknowledges from its own scoped identity by supplying an `outcome`. Acknowledging with `DELIVERED` succeeds only while the logical clock is still strictly before the showtime's `starts_at` — an acknowledgment at or after the feature's start is rejected with `ERR_DELIVERY_LATE` (HTTP 422) — and moves the reel `IN_TRANSIT → DELIVERED`. Reporting `FAILED` instead moves the reel `IN_TRANSIT → DELIVERY_FAILED`. A failed delivery is not terminal: dispatching again from `DELIVERY_FAILED` returns the reel to `IN_TRANSIT` for another attempt.

Once the house lights dim, verification begins. For each `CONFIRMED` slot the theater records one playback outcome against the `slot_id` in the path; the record is append-only, and at most one PlayLog may exist per slot. Recording is theater-scoped and time-gated: the logical clock must be at or after the showtime's `starts_at`, or the record is rejected with `ERR_PLAYLOG_BEFORE_SHOWTIME` (HTTP 422). When both a duplicate record and a wrong slot state would apply, the duplicate check speaks first — an existing PlayLog for the slot yields `ERR_PLAYLOG_ALREADY_RECORDED` — and only otherwise does a slot not in `CONFIRMED` yield `ERR_PLAYLOG_SLOT_NOT_CONFIRMED`.

Each PlayLog carries the recording operator's `reported_by_user_id` and the `reported_by_theater_id` resolved from that identity, and stamps `played_at` with the logical clock's value at record time. The recorded `outcome` drives the slot's fork. `VERIFIED` and `PARTIAL` both move the slot `CONFIRMED → PLAYED`; `FAILED` moves it `CONFIRMED → MISSED`. On a played slot the system sets `play_factor` — 1.0 for `VERIFIED`; for `PARTIAL`, 0.5 when the campaign's `partial_credit_mode` is `STRICT` but the full 1.0 when it is `LENIENT` — and, whenever the showtime's `actual_attendance` is already known, sets `attributed_impressions` to the floor of `actual_attendance` multiplied by `play_factor`, leaving the attribution null while attendance is unknown. A failed slot instead takes a `play_factor` of 0.0 and an `attributed_impressions` of 0. Either way, the campaign's `delivered_impressions` is immediately recomputed, adding the new contribution or dropping the missed slot's. A slot's playback records can be listed, returning an array of zero or one element.

After the last creative has aired, `NetworkOps` reconciles the reel. Reconciliation is defined only from `DELIVERED` — an attempt against a reel in any other state is rejected with `ERR_INVALID_STATE_TRANSITION` — and only once every `CONFIRMED` slot has received its playback record: while any `CONFIRMED` slot remains, the request is rejected with `ERR_REEL_NOT_RECONCILABLE`. A successful reconciliation moves the reel `DELIVERED → RECONCILED`, which is terminal.

### 3.5. Counting the House: Attendance Reporting, Review, and Audit

Playback tells the network what aired; attendance tells it who saw it. After the showtime, the theater files an attendance report against the `showtime_id` in the path, carrying its `reported_attendance`, a count at or above zero. Filing is theater-scoped, records `reported_by_user_id` from the caller's header identity, and is refused with `ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT` while any earlier report for the same showtime still sits in `SUBMITTED` or `ACCEPTED`. A new report's `report_status` opens at `SUBMITTED`, and a showtime's reports can be listed by any role.

`NetworkOps` then reviews the filing by supplying a `decision`. An `ACCEPT` decision moves the report `SUBMITTED → ACCEPTED`, stamps `reviewed_by_user_id`, and — critically — sets the showtime's `actual_attendance` to the report's `reported_attendance`. That assignment cascades immediately: every `PLAYED` slot on the showtime recomputes its `attributed_impressions` from the new figure, and every affected campaign recomputes its `delivered_impressions`. A `DISPUTE` decision instead moves the report `SUBMITTED → DISPUTED`, likewise stamps `reviewed_by_user_id`, and leaves the showtime's figure untouched.

A disputed report is corrected by the same scoped theater: resubmission carries a fresh `reported_attendance`, returns the report `DISPUTED → SUBMITTED`, and clears `reviewed_by_user_id` so the review cycle begins again.

Finality comes from an `Auditor`, who establishes the `audited_attendance` — a count at or above zero, which may revise the reported figure upward or downward. Audit requires the report to be in `ACCEPTED`; auditing a report in any other state is rejected with `ERR_ATTENDANCE_NOT_AUDITABLE`. Segregation of duties also forbids auditing one's own filing: when the caller's identity equals the report's `reported_by_user_id`, the audit is rejected with `ERR_SOD_AUDITOR_IS_REPORTER`. A successful audit moves the report `ACCEPTED → AUDITED`, stamps `audited_by_user_id`, rewrites the showtime's `actual_attendance` to the `audited_attendance`, and re-runs the same attribution and delivery cascades as an acceptance. `AUDITED` is terminal, and an audited figure is what downstream certification trusts.

### 3.6. Billing the Flight: Invoices from Provisional Snapshot to Certified Settlement

Billing is campaign-scoped and period-based. A `SalesManager` generates an invoice by supplying a `period_start_date` and a `period_end_date` — the end must not precede the start — with the billed campaign fixed by the `campaign_id` in the path. The new period must not overlap the period of any existing non-`VOID` invoice of the same campaign, or creation is rejected with `ERR_INVOICE_PERIOD_OVERLAP`. Creation snapshots the provisional, forecast-based picture: the covered lines are the campaign's slots in `RESERVED`, `CONFIRMED`, or `PLAYED` whose showtime's calendar date falls within the period, endpoints inclusive, with `MISSED` and `CANCELED` slots contributing nothing. `provisional_impressions` sums, per covered slot, that slot's showtime's `forecast_attendance` — two covered slots on the same showtime each contribute its forecast — and `provisional_amount_cents` sums one line per covered slot of `forecast_attendance` multiplied by `cpm_cents` and divided by 1000, each line rounded half-up to a whole cent before the lines are summed, per the pinned rounding order of §2.9. An invoice is born with `billing_status` `DRAFT` and `audit_status` `UNAUDITED` — two independent state dimensions that advance separately — with `applied_credit_cents` at zero and `audited_impressions`, `audited_amount_cents`, and `final_amount_cents` all null. A campaign's invoices can be listed, and an invoice read back with its `version` exposed for the concurrency rule of §2.8.

Issuing moves the billing dimension `DRAFT → ISSUED` and stamps `issued_by_user_id`. Certification is the audit dimension's only transition, and it is heavily guarded: the audit dimension must still be `UNAUDITED` — certifying an already-`CERTIFIED` invoice is rejected with `ERR_INVALID_STATE_TRANSITION` — the invoice's billing must stand at `ISSUED`; every slot of the campaign on showtimes dated within the period must have reached `PLAYED` or `MISSED`; and every showtime carrying an in-period slot must have its latest attendance report in `ACCEPTED` or `AUDITED`. Any shortfall in those conditions is rejected with `ERR_INVOICE_NOT_CERTIFIABLE`. Segregation of duties additionally bars the issuer from certifying: a caller whose identity equals `issued_by_user_id` is rejected with `ERR_SOD_CERTIFIER_IS_ISSUER`. Certification computes the audited picture over the same period: the covered lines are now only `PLAYED` slots, `audited_impressions` is the sum of their `attributed_impressions` with slots whose attribution is still null contributing zero, and `audited_amount_cents` sums one line per slot of `attributed_impressions` multiplied by `cpm_cents` and divided by 1000, each line again rounded half-up before summing. Upon certification `final_amount_cents` is set equal to `audited_amount_cents`, `certified_by_user_id` is stamped, and the audit dimension moves `UNAUDITED → CERTIFIED`.

Settlement closes the money. Settling requires the audit dimension to be `CERTIFIED` and no make-good credit of this invoice to be open in `PROPOSED` or `APPROVED`; either shortfall is rejected as `ERR_INVOICE_NOT_SETTLABLE`. A successful settle moves the billing dimension `ISSUED → SETTLED`. An invoice can instead be abandoned: voiding is defined while billing is `DRAFT` or `ISSUED`, but only while the audit dimension is still `UNAUDITED` — voiding a certified invoice is rejected with `ERR_INVALID_STATE_TRANSITION` — and it moves billing to `VOID`, freeing its period so a future invoice may cover those dates again.

### 3.7. Making Good: Under-Delivery Credits

When a certified invoice reveals under-delivery, an `Auditor` may propose a make-good credit against it, with the target invoice fixed by the `invoice_id` in the path. Proposal requires the invoice's audit dimension to be `CERTIFIED` and no earlier make-good of the same invoice to be open in `PROPOSED` or `APPROVED`; otherwise the proposal is rejected with `ERR_INVALID_STATE_TRANSITION`. The proposal measures the shortfall at that instant: `shortfall_impressions` is the campaign's `contracted_impressions` minus its current `delivered_impressions`, floored at zero, and `under_delivery_pct` is that shortfall divided by `contracted_impressions`. Eligibility is a strict threshold — the ratio must be greater than 0.05, so a campaign under-delivered by exactly five percent earns nothing and the proposal is rejected with `ERR_MAKE_GOOD_THRESHOLD_NOT_MET` (HTTP 422). The offered `credit_cents` is the shortfall multiplied by the campaign's `cpm_cents`, then multiplied by 1.10, divided by 1000, and rounded half-up to a whole cent — capped at the invoice's `audited_amount_cents`, so the credit never exceeds the audited bill. The credit lands with `credit_status` `PROPOSED` and `proposed_by_user_id` stamped, and an invoice's make-goods can be listed by any role.

A second `Auditor` reviews the proposal by supplying a `decision`: `APPROVE` moves the credit `PROPOSED → APPROVED`, while `DECLINE` moves it `PROPOSED → DECLINED`, and either outcome stamps `reviewed_by_user_id`. The reviewer must differ from the proposer — an overlap is rejected with `ERR_SOD_REVIEWER_IS_PROPOSER` — and reviewing a credit that has left `PROPOSED` is rejected with `ERR_MAKE_GOOD_NOT_REVIEWABLE`. `DECLINED` is terminal and, unlike an open credit, does not block settlement of the invoice.

Posting the credit is the sales desk's job, and it is version-guarded. The application must carry `expected_invoice_version` matching the invoice's current `version`, with a stale value rejected as `ERR_STALE_VERSION` (HTTP 412); the credit itself must be `APPROVED`, with any other state rejected as `ERR_MAKE_GOOD_NOT_REVIEWABLE`; and the invoice must stand `ISSUED` in its billing dimension and `CERTIFIED` in its audit dimension, with any other combination rejected as `ERR_INVALID_STATE_TRANSITION`. Application moves the credit `APPROVED → APPLIED`, adds its `credit_cents` into the invoice's `applied_credit_cents`, and subtracts the same amount from the invoice's `final_amount_cents`, preserving the invariant that `final_amount_cents` plus `applied_credit_cents` always equals `audited_amount_cents`. It also stamps `applied_by_user_id` and increments the invoice's `version` by one — the very mutation the next applicant's `expected_invoice_version` must observe. Because an invoice with a credit still open in `PROPOSED` or `APPROVED` cannot settle, this loop ties directly back into the settlement gate of §3.6.

## 4. Endpoint Definitions

Endpoints that create a new resource — a theater, screen, feature, showtime, advertiser, campaign, slot, playback record, attendance report, invoice, or make-good credit — answer `201 Created`. Endpoints that act on an existing resource, including every state transition, edit, review, and acknowledgment, answer `200 OK`. All responses follow the envelope of §2.2, and failures answer with the error format there using the identifiers catalogued in §5.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/network/_clock/set_current_utc` | Set the logical clock | NetworkOps |
| POST | `/network/theaters` | Create a theater | NetworkOps |
| GET | `/network/theaters/{theater_id}` | Get a theater | All roles |
| POST | `/network/theaters/{id}/screens` | Add a screen (auditorium) to a theater | NetworkOps |
| GET | `/network/screens/{screen_id}` | Get a screen | All roles |
| GET | `/network/theaters/{id}/screens` | List a theater's screens | All roles |
| POST | `/network/features` | Register a film | NetworkOps |
| GET | `/network/features/{feature_id}` | Get a feature | All roles |
| POST | `/network/screens/{screen_id}/showtimes` | Schedule a showtime on a screen; auto-creates its empty ASSEMBLING pre-show reel; rejects buffered overlap on the screen | NetworkOps |
| GET | `/network/showtimes/{showtime_id}` | Get a showtime | All roles |
| GET | `/network/showtimes` | List showtimes with optional filters | All roles |
| GET | `/network/showtimes/{id}/reel` | Get the showtime's pre-show reel (array of 0-1) | All roles |
| GET | `/network/reels/{reel_id}` | Get a reel (includes version for OCC) | All roles |
| POST | `/network/advertisers` | Create an advertiser | SalesManager |
| GET | `/network/advertisers/{advertiser_id}` | Get an advertiser | All roles |
| POST | `/network/campaigns` | Create a campaign in DRAFT | SalesManager |
| GET | `/network/campaigns/{campaign_id}` | Get a campaign | All roles |
| GET | `/network/advertisers/{id}/campaigns` | List an advertiser's campaigns | All roles |
| PATCH | `/network/campaigns/{campaign_id}` | Edit a campaign; only in DRAFT or REJECTED; editing a REJECTED campaign reopens it to DRAFT | SalesManager |
| POST | `/network/campaigns/{campaign_id}/submit` | Submit a DRAFT campaign for approval | SalesManager |
| POST | `/network/campaigns/{campaign_id}/approve` | Approve a SUBMITTED campaign; approver must differ from creator (SoD) | SalesManager |
| POST | `/network/campaigns/{campaign_id}/reject` | Reject a SUBMITTED campaign; rejecter must differ from creator (SoD) | SalesManager |
| POST | `/network/campaigns/{campaign_id}/cancel` | Cancel a campaign in DRAFT, SUBMITTED, or APPROVED with no RESERVED/CONFIRMED slots | SalesManager |
| POST | `/network/campaigns/{campaign_id}/complete` | Complete an APPROVED campaign once all slots are terminal and no open invoices | SalesManager |
| POST | `/network/reels/{reel_id}/slots` | Reserve a slot in an ASSEMBLING reel (OCC on reel version) | SalesManager |
| GET | `/network/slots/{slot_id}` | Get a slot | All roles |
| GET | `/network/slots` | List slots with optional filters | All roles |
| POST | `/network/slots/{slot_id}/cancel` | Cancel a RESERVED slot while the reel is still ASSEMBLING | SalesManager |
| POST | `/network/reels/{reel_id}/lock` | Lock an ASSEMBLING reel (OCC on reel version); all RESERVED slots become CONFIRMED | NetworkOps |
| POST | `/network/reels/{reel_id}/dispatch` | Dispatch a LOCKED reel to the theater; also redelivers from DELIVERY_FAILED | NetworkOps |
| POST | `/network/reels/{reel_id}/acknowledge-delivery` | Theater acknowledges delivery (outcome=DELIVERED) or reports failure (outcome=FAILED); must occur before showtime start | TheaterOps |
| POST | `/network/reels/{reel_id}/reconcile` | Reconcile a DELIVERED reel once every CONFIRMED slot has a PlayLog outcome | NetworkOps |
| POST | `/network/slots/{id}/playlogs` | Record playback outcome for a CONFIRMED slot; at most one PlayLog per slot | TheaterOps |
| GET | `/network/slots/{id}/playlogs` | List a slot's playlogs (array of 0-1) | All roles |
| POST | `/network/showtimes/{id}/attendance-reports` | Theater submits actual attendance for a showtime | TheaterOps |
| GET | `/network/showtimes/{id}/attendance-reports` | List a showtime's attendance reports | All roles |
| POST | `/network/attendance-reports/{report_id}/review` | NetworkOps accepts (actual_attendance takes effect) or disputes a SUBMITTED report | NetworkOps |
| POST | `/network/attendance-reports/{report_id}/resubmit` | Theater resubmits a DISPUTED report with a corrected figure (report returns to SUBMITTED) | TheaterOps |
| POST | `/network/attendance-reports/{report_id}/audit` | Auditor establishes final audited attendance (may revise); auditor must differ from reporter (SoD) | Auditor |
| POST | `/network/campaigns/{id}/invoices` | Generate a DRAFT invoice with provisional forecast-based snapshot for a period | SalesManager |
| GET | `/network/invoices/{invoice_id}` | Get an invoice (includes version for OCC) | All roles |
| GET | `/network/campaigns/{id}/invoices` | List a campaign's invoices | All roles |
| POST | `/network/invoices/{invoice_id}/issue` | Issue a DRAFT invoice | SalesManager |
| POST | `/network/invoices/{invoice_id}/certify` | Auditor certifies an ISSUED invoice: computes audited amounts (per-line rounding); certifier must differ from issuer (SoD) | Auditor |
| POST | `/network/invoices/{invoice_id}/settle` | Settle an ISSUED + CERTIFIED invoice with no open make-goods | SalesManager |
| POST | `/network/invoices/{invoice_id}/void` | Void a DRAFT or ISSUED invoice while still UNAUDITED | SalesManager |
| POST | `/network/invoices/{id}/make-goods` | Auditor proposes an under-delivery make-good credit against a CERTIFIED invoice | Auditor |
| GET | `/network/invoices/{id}/make-goods` | List an invoice's make-good credits | All roles |
| POST | `/network/make-goods/{make_good_id}/review` | Second Auditor approves or declines a PROPOSED make-good; reviewer must differ from proposer (SoD) | Auditor |
| POST | `/network/make-goods/{make_good_id}/apply` | SalesManager applies an APPROVED make-good to its invoice (OCC on invoice version) | SalesManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_THEATER_SCOPE_MISMATCH` | 403 Forbidden |
| `ERR_SOD_APPROVER_IS_CREATOR` | 403 Forbidden |
| `ERR_SOD_CERTIFIER_IS_ISSUER` | 403 Forbidden |
| `ERR_SOD_AUDITOR_IS_REPORTER` | 403 Forbidden |
| `ERR_SOD_REVIEWER_IS_PROPOSER` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_CAMPAIGN_NOT_BOOKABLE` | 409 Conflict |
| `ERR_CAMPAIGN_HAS_ACTIVE_SLOTS` | 409 Conflict |
| `ERR_CAMPAIGN_HAS_OPEN_INVOICES` | 409 Conflict |
| `ERR_REEL_NOT_ASSEMBLING` | 409 Conflict |
| `ERR_REEL_NOT_LOCKABLE` | 409 Conflict |
| `ERR_REEL_NOT_RECONCILABLE` | 409 Conflict |
| `ERR_PLAYLOG_SLOT_NOT_CONFIRMED` | 409 Conflict |
| `ERR_PLAYLOG_ALREADY_RECORDED` | 409 Conflict |
| `ERR_ATTENDANCE_NOT_AUDITABLE` | 409 Conflict |
| `ERR_DUPLICATE_OPEN_ATTENDANCE_REPORT` | 409 Conflict |
| `ERR_INVOICE_NOT_CERTIFIABLE` | 409 Conflict |
| `ERR_INVOICE_NOT_SETTLABLE` | 409 Conflict |
| `ERR_INVOICE_PERIOD_OVERLAP` | 409 Conflict |
| `ERR_MAKE_GOOD_NOT_REVIEWABLE` | 409 Conflict |
| `ERR_RATING_PLACEMENT_VIOLATION` | 422 Unprocessable Entity |
| `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` | 409 Conflict |
| `ERR_SLOT_INTERVAL_OVERLAP` | 409 Conflict |
| `ERR_POOL_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_SHOWTIME_OVERLAP` | 409 Conflict |
| `ERR_OUTSIDE_FLIGHT_WINDOW` | 422 Unprocessable Entity |
| `ERR_DELIVERY_LATE` | 422 Unprocessable Entity |
| `ERR_PLAYLOG_BEFORE_SHOWTIME` | 422 Unprocessable Entity |
| `ERR_BUDGET_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_MAKE_GOOD_THRESHOLD_NOT_MET` | 422 Unprocessable Entity |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
