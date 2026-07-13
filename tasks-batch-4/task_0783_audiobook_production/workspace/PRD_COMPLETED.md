# Audiobook Production API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for a backend service that orchestrates the full audiobook lifecycle, from a rights holder registering a title through narrator casting, studio production, quality control, retail distribution, and royalty settlement. The domain mirrors the workflows of production-and-distribution platforms such as ACX and Findaway: an author brings the rights to a book, a narrator auditions and is cast under either a royalty-share or a per-finished-hour deal, the finished audio moves through quality-control review, and once published it is listed on retail channels where sales accrue royalties that are periodically statemented and paid out.

The service exists to make a fundamentally multi-party negotiation auditable and financially consistent. Several parties act on the same title over its life — the author who owns the rights, one or more narrators who audition and produce, quality-control reviewers who gate delivery, and the platform operator who runs distribution and money movement — and each transition must leave the system in a state that every other party can trust. Money in particular is never invented or lost: every credit to an author or narrator balance is the exact integer-cent counterpart of a paid statement, and every reversal debits precisely what was credited.

Because the same title can be re-offered, revised, republished, and ultimately have its rights reverted, the platform treats state transitions and cross-entity cascades as first-class concerns. A single act — such as an author reverting rights on a published title — can ripple through the contract, the live retail listings, and any open royalty statements. The remainder of this document defines the entities, the global contracts every endpoint honors, the business workflows and their scattered rules, the endpoint surface, and the error catalogue.

## 2. Global Specifications & System-Wide Principles

### 2.1. User Roles and Access Control

Every request must carry two headers: `X-User-ID`, identifying the acting principal, and `X-User-Role`, naming the principal's role. If either header is missing, or if `X-User-Role` is not one of the known roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401) before any other processing. When the headers are well-formed but the role is not permitted to invoke the requested operation, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

The system recognizes exactly four roles: `Author`, `Narrator`, `QCReviewer`, and `PlatformAdmin`.

Two of these roles are **entity-backed**, meaning the value in `X-User-ID` is the identity of a persisted record and is used for ownership checks:

- When `X-User-Role` is `Author`, `X-User-ID` is the `id` of the acting `Author`. Ownership checks on any resource that references an author compare that resource's `author_id` (directly, as on a `Title`, or transitively through the title a resource belongs to) against `X-User-ID`. An author may only open, sample, publish-eligibility-drive, revert, or cast against titles it owns, and may only decide auditions on its own titles.
- When `X-User-Role` is `Narrator`, `X-User-ID` is the `id` of the acting `Narrator`. Ownership checks compare the resource's `narrator_id` — on an `Audition`, a `Contract`, a `ProductionBooking`, or the contract behind a `ProductionMilestone` — against `X-User-ID`.

The other two roles are **opaque** operator identities:

- When `X-User-Role` is `QCReviewer`, `X-User-ID` is an opaque reviewer identifier not tied to any persisted entity. The server does not compare it to any entity's `id`; a reviewer may act on any milestone review it is permitted to invoke.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. Platform administrators run onboarding, distribution, sales ingestion, royalty payout, and the test clock without ownership restriction.

When an entity-backed caller invokes an operation that mutates a resource it does not own, the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403), the same code used for a disallowed role. The publish operation is the one place an administrator is explicitly exempt from author ownership: publication is an operator action, not an owner action.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. The `limit` defaults to 10 when omitted, with a minimum of 1 and a maximum of 100; a requested limit above 100 is capped at 100. The `offset` defaults to 0 and represents the number of leading records to skip. List results are ordered by creation sequence — the order in which records were persisted — so that records surface in the order they were created; because the logical clock can be set to arbitrary instants, this creation order is authoritative even where it diverges from the `created_at` value ordering. The `meta` block of a list response reports `limit`, `offset`, `total_count` (the number of records matching the filter before pagination), and `has_more` (true when records remain beyond the current page).

### 2.4. Resource Identity, Common Fields, and Versioning

Every persisted resource carries a server-minted `id` that is a UUID with no type prefix, and a `created_at` timestamp recorded as an ISO 8601 UTC string with three fractional digits. Most resources additionally carry an `updated_at` timestamp (same format, refreshed on every mutation) and an integer `version` that starts at 1 on creation and increments by exactly 1 on every mutation that changes the resource. Whenever a state transition or side effect below says a resource's version is bumped, that means `version` increases by one and `updated_at` is refreshed to the current logical time.

Two resource types are deliberately lightweight and carry only `id` and `created_at` — they have neither an `updated_at` nor a `version` field, because they are immutable audit records once written: the `QCReview` (a recorded quality-control verdict) and the `SalesEvent` (a recorded sales line). All other resources — `Author`, `Narrator`, `Title`, `Audition`, `Contract`, `ProductionBooking`, `ProductionMilestone`, `DistributionChannel`, `DistributionListing`, and `RoyaltyStatement` — carry the full complement of `created_at`, `updated_at`, and `version`.

### 2.5. Optimistic Concurrency on Contract Offers

Offering a contract against a title is guarded by optimistic concurrency so that a rights holder never blindly overwrites a casting decision it has not seen. A contract-offer request must include `expected_title_version`, carrying the client's last observed `version` of the target `Title`. The server compares `expected_title_version` against the title's current `version`; if they do not match, the offer is rejected with `ERR_STALE_TITLE_VERSION` (HTTP 412). A mismatch means another writer has advanced the title since the client last read it — most importantly, another author action has already offered a contract on this title, legitimately superseding any prior outstanding offer and bumping the title's version — so the current caller's view is stale and its offer must not land. This is the only endpoint that consumes a version field; no other write accepts or requires an `expected_*_version` input.

### 2.6. Referential Existence and Left-to-Right Path Resolution

Before any business rule runs, every resource referenced by the request — whether named in the URL path or in the request body — must exist. References are resolved left-to-right in path order, then body order, and the first missing reference determines the error. Each reference has its own concretized not-found error and all of them return HTTP 404: a missing `author_id` yields `ERR_AUTHOR_NOT_FOUND`, a missing `narrator_id` yields `ERR_NARRATOR_NOT_FOUND`, a missing `title_id` yields `ERR_TITLE_NOT_FOUND`, a missing audition reference yields `ERR_AUDITION_NOT_FOUND`, a missing `contract_id` yields `ERR_CONTRACT_NOT_FOUND`, a missing booking reference yields `ERR_BOOKING_NOT_FOUND`, a missing `milestone_id` yields `ERR_MILESTONE_NOT_FOUND`, a missing `channel_id` yields `ERR_CHANNEL_NOT_FOUND`, a missing `listing_id` yields `ERR_LISTING_NOT_FOUND`, and a missing statement reference yields `ERR_STATEMENT_NOT_FOUND`. Because `QCReview` and `SalesEvent` have no dedicated concretized not-found code, a missing reference to either — as when reading one by `id` — yields the generic `ERR_RESOURCE_NOT_FOUND` (HTTP 404). A malformed body, a missing required field, or a bad type or enum value is rejected earlier with `ERR_VALIDATION` (HTTP 400).

### 2.7. Monetary Precision and Rounding

All money is stored and returned as integer cents. Wherever a monetary figure is derived by multiplying by a fraction — a retailer cut, a narrator share, a per-hour fee — the result is rounded half up to the nearest whole cent. Rounding is applied per line before summation, never after: when a royalty statement aggregates multiple sales lines, each line's net is rounded to whole cents first and only then are the rounded line nets summed (round-then-sum, not sum-then-round). Shares and percentages themselves are ratios carried at full precision; only the derived cent amounts are rounded.

### 2.8. Rights Integrity and Cascade Consistency

A title's `rights_status` is the master switch for whether the rights holder still controls distribution; it begins `ACTIVE` and can move to `REVERTED`. Any production or distribution mutation on a title whose `rights_status` is `REVERTED` is refused with `ERR_RIGHTS_REVERTED` (HTTP 409). When a title's rights are reverted, the change is not isolated to the title: it is the root of a cascade that terminates the active contract, withdraws every live retail listing, and freezes every open royalty statement, as detailed in the rights-reversion workflow. Each entity touched by a cascade has its own `version` bumped and `updated_at` refreshed, exactly as if it had been mutated directly.

### 2.9. Validation Ordering

When several checks could apply to one request, they are evaluated in a fixed priority order so that the reported error is deterministic. The order is: (1) authentication of the headers (`ERR_UNAUTHENTICATED`); (2) role permission for the endpoint (`ERR_UNAUTHORIZED`); (3) existence of every referenced resource, left-to-right (the concretized not-found errors); (4) ownership by the acting entity-backed user (`ERR_UNAUTHORIZED`); (5) the target title's rights still being `ACTIVE` for production or distribution mutations (`ERR_RIGHTS_REVERTED`); (6) the target resource being in the correct state for the requested transition (the concretized invalid-state errors); (7) the optimistic-concurrency version check on contract offers (`ERR_STALE_TITLE_VERSION`); (8) cross-entity linkage such as an accepted audition, an accepted contract, or a supported territory (`ERR_AUDITION_NOT_ACCEPTED`, `ERR_CONTRACT_NOT_ACCEPTED`, `ERR_TERRITORY_NOT_SUPPORTED`); (9) deal-type field coherence (`ERR_DEAL_TYPE_FIELDS`); (10) date, window, and quantity validity (`ERR_INVALID_DATE_RANGE`, `ERR_SAMPLE_TOO_LONG`, `ERR_INVALID_FINISHED_HOURS`); (11) temporal overlap for bookings and listing gaps (`ERR_BOOKING_OVERLAP`, `ERR_LISTING_GAP_CONFLICT`); and finally (12) the fiscal check that a payout has something to pay (`ERR_NOTHING_TO_PAY`). An earlier check always masks a later one — for example, a caller acting on a resource it does not own is told `ERR_UNAUTHORIZED` (priority 4) rather than a state error, and a reverted title surfaces `ERR_RIGHTS_REVERTED` (priority 5) before any transition-state check.

### 2.10. The Logical Clock

The server keeps a logical UTC clock used for defaulting a sales event's `occurred_at`, for windowing statements over an accounting period, and as the source of every server-minted timestamp — each resource's `created_at` and `updated_at` and each response's `api_request_timestamp` all read from this logical clock rather than wall-clock time. On startup the clock reads exactly `2026-03-01T00:00:00Z` and never falls back to wall-clock time; before any clock-setting call it holds precisely this default. An administrative test-driving capability sets the clock to a supplied instant, supplied as the `to_iso8601` field.

## 3. Business Logic & Workflows

### 3.1. Onboarding Authors, Narrators, and Titles

The platform operator onboards the two entity-backed parties. Registering an author records a `name` and a contact `email`, where the email must be unique across all authors (a duplicate email is rejected with `ERR_VALIDATION`); the new author begins with a `payout_balance_cents` of 0, a running total of the royalty and production earnings credited to that author. Registering a narrator records a `name`, a unique-across-narrators `email` (a duplicate email is likewise rejected with `ERR_VALIDATION`), and an `hourly_rate_cents` — the narrator's default per-finished-hour rate, which must be zero or greater. A narrator likewise starts with a `payout_balance_cents` of 0 and an `active_booked_days` of 0; both are computed running totals maintained by the system rather than client inputs. When reading a narrator, the response exposes both `payout_balance_cents` and `active_booked_days`; reading an author exposes `payout_balance_cents`.

An author creates a title to begin the lifecycle. The creating author supplies a `title_name`, an `isbn` print reference, an `exclusivity` grant that is either `EXCLUSIVE` or `NON_EXCLUSIVE`, a `territory` in which distribution rights are granted that is one of `WORLD`, `US`, `UK`, or `EU`, and a suggested `list_price_cents` that must be strictly greater than zero. The title's `author_id` is taken from `X-User-ID` rather than the body, binding ownership to the caller. A new title is born in `DRAFT` status with `rights_status` of `ACTIVE`. Its `finished_hours` is 0 until a full deliverable is approved, and its `retail_sample_start_sec` and `retail_sample_end_sec` are both unset until a sample window is chosen. Titles can be listed with optional `author_id` and `status` filters.

Once a draft is ready to receive narrators, the owning author opens it, advancing the title `DRAFT → OPEN_FOR_AUDITION`. Opening requires that the caller owns the title and that its `rights_status` is still `ACTIVE`, and it bumps the title's version. Attempting to open a title that is not in `DRAFT` has no matching transition and is refused with `ERR_INVALID_STATE`.

Later in the lifecycle, after the finished audio exists, the owning author sets the retail sample clip window on the title by supplying `retail_sample_start_sec` and `retail_sample_end_sec`. The sample is measured in seconds within the finished audio; the clip length is the end second minus the start second, treating the end as exclusive. The length must be strictly positive and at most `MAX_RETAIL_SAMPLE_SEC`, which is 300 seconds (five minutes); a length of zero or below, or one exceeding 300 seconds, is rejected with `ERR_SAMPLE_TOO_LONG`. Setting the sample bumps the title's version.

### 3.2. Auditions and Casting Decisions

A narrator auditions for a title that is open. Submitting an audition records the `title_id` being auditioned for, the `narrator_id` (taken from `X-User-ID`), and a `sample_url` pointing at the submitted sample; the new audition begins in `SUBMITTED` status. An audition may only be submitted while the target title is in `OPEN_FOR_AUDITION` — otherwise the submission is refused with `ERR_TITLE_NOT_OPEN` — and, like all production mutations, only while the title's rights remain `ACTIVE`. Auditions can be listed and filtered by `title_id`, by `narrator_id`, and by `status`.

The owning author then decides each audition by supplying a `decision` whose value is the literal `ACCEPT` or `DECLINE`. Accepting moves the audition `SUBMITTED → ACCEPTED`; declining moves it `SUBMITTED → DECLINED`. Both require that the caller owns the title behind the audition, and both bump the audition's version. Accepting additionally requires that the title is still in `OPEN_FOR_AUDITION` at decision time; accepting when the title has left `OPEN_FOR_AUDITION` is refused with `ERR_TITLE_NOT_OPEN`. A decision may only be rendered on an audition still in `SUBMITTED`; a decision on an already-decided audition is refused with `ERR_AUDITION_NOT_SUBMITTED`. An `ACCEPTED` audition is the gate that lets the author later offer a contract to that particular narrator — casting cannot proceed for a narrator who has not been accepted.

### 3.3. Offering Contracts and Choosing a Deal Model

Casting a title means offering a contract to an accepted narrator. The author supplies the `title_id`, the `narrator_id` being cast, the `deal_type`, the concurrency token `expected_title_version`, and exactly one compensation figure depending on the deal. A `deal_type` of `ROYALTY_SHARE` requires `royalty_share_pct` — the narrator's base share of net royalties, which must be greater than 0 and at most 0.50 (a supplied value outside `(0, 0.50]` is rejected with `ERR_VALIDATION`, distinct from the deal-coherence check) — and forbids `per_hour_rate_cents`. A `deal_type` of `PER_HOUR` requires `per_hour_rate_cents` — a per-finished-hour production fee in cents, which must be strictly greater than zero (a non-positive value is rejected with `ERR_VALIDATION`) — and forbids `royalty_share_pct`; this per-hour rate on the contract overrides the narrator's listed `hourly_rate_cents`. Supplying the wrong field for the deal type, or omitting the required one, is a deal-coherence failure rejected with `ERR_DEAL_TYPE_FIELDS`. Offering also requires that an `ACCEPTED` audition exists for this exact title-and-narrator pairing; without it the offer is refused with `ERR_AUDITION_NOT_ACCEPTED`.

An offer is only valid while the title's rights are `ACTIVE`, and it is guarded by the optimistic-concurrency check described in §2.5: `expected_title_version` must equal the title's current `version`, or the offer is rejected with `ERR_STALE_TITLE_VERSION`. A successful offer creates the contract in `OFFERED` status and bumps the title's version. Offering is only accepted while the title is in `OPEN_FOR_AUDITION` or `CASTING`; an offer against a title in any other status is refused with `ERR_INVALID_STATE`. When the title is in `OPEN_FOR_AUDITION`, the first offer advances it `OPEN_FOR_AUDITION → CASTING`. A title already in `CASTING` stays in `CASTING` on a re-offer, but the re-offer supersedes the outstanding offer: any existing `OFFERED` contract on that title is moved `OFFERED → SUPERSEDED` as the new `OFFERED` contract is created. Contracts can be listed and filtered by `title_id`, by `narrator_id`, and by `status`.

The cast narrator responds to an offer with a `decision` whose value is the literal `ACCEPT` or `DECLINE`. Accepting a contract moves it `OFFERED → ACCEPTED` and drives the title `CASTING → IN_PRODUCTION`, opening the door to production delivery; the contract's version is bumped. Declining moves the contract `OFFERED → DECLINED` and returns the title `CASTING → OPEN_FOR_AUDITION` so the author can cast someone else. Both responses require that the caller is the contract's narrator and that the contract is still `OFFERED`; a response to a contract that is not `OFFERED` is refused with `ERR_CONTRACT_NOT_OFFERED`.

### 3.4. Reserving Production Time

A narrator reserves studio and production time by booking a window against a title. The booking records the `narrator_id` (taken from `X-User-ID`), the `title_id` the narrator will produce, and a `start_date` and `end_date` in `YYYY-MM-DD` form. The window is half-open, `[start_date, end_date)`: the start date is inclusive and the end date exclusive. The start must precede the end; a booking whose `start_date` is not strictly before its `end_date` is rejected with `ERR_INVALID_DATE_RANGE`. A new booking begins in `ACTIVE` status. A booking may be reserved against any existing title regardless of that title's `status` or `rights_status`; the booking endpoint applies no title-state or rights-reversion gate.

Because the window is half-open, two bookings that merely touch at an endpoint — where one's `end_date` equals the next one's `start_date` — do not conflict; only a true interior overlap is forbidden. A new `ACTIVE` booking that interior-overlaps an existing `ACTIVE` booking for the same narrator is rejected with `ERR_BOOKING_OVERLAP`. Bookings that are `CANCELLED` or `COMPLETED` never participate in the overlap test. Bookings can be listed and filtered by `narrator_id`, by `title_id`, and by `status`.

The narrator's `active_booked_days` is the sum, over that narrator's `ACTIVE` bookings only, of each booking's whole-day span — the end date minus the start date, which because the end is exclusive equals the number of days in the `[start_date, end_date)` interval. Cancelled and completed bookings are excluded. This total is recomputed whenever a booking is created, cancelled, or completed. A narrator cancels an `ACTIVE` booking it owns, moving it `ACTIVE → CANCELLED` (cancelling a booking that is not `ACTIVE` is refused with `ERR_INVALID_STATE`), releasing its days back (the `active_booked_days` total is recomputed downward) and bumping the booking's version. The system also completes a booking automatically: when the booking's title reaches `PUBLISHED`, every `ACTIVE` booking for that title is moved `ACTIVE → COMPLETED`, which likewise releases its days and bumps the booking's version.

### 3.5. Delivering Milestones and Quality Control

Under an accepted contract the narrator delivers production milestones. A milestone submission carries the `contract_id` it delivers against, a `milestone_type` that is either `FIFTEEN_MIN` (an early fifteen-minute checkpoint) or `FULL` (the complete finished audiobook), an `audio_url` for the deliverable, and — for a `FULL` deliverable only — a `finished_hours` figure declaring the finished running time. Submitting requires that the contract is in `ACCEPTED` status, or the submission is refused with `ERR_CONTRACT_NOT_ACCEPTED`, and the caller must be that contract's narrator. For a `FULL` milestone, `finished_hours` is required and must be strictly greater than zero; a missing or non-positive value is rejected with `ERR_INVALID_FINISHED_HOURS`. For a `FIFTEEN_MIN` milestone, `finished_hours` is ignored. Every new milestone begins in `SUBMITTED` status with a `revision_count` of 0. Submitting a `FULL` milestone advances the title `IN_PRODUCTION → IN_QC` and bumps the title's version; a `FIFTEEN_MIN` submission leaves the title in `IN_PRODUCTION`. Milestones can be listed and filtered by `contract_id` and by `status`.

A quality-control reviewer records a verdict on a submitted milestone by supplying an `outcome` of `PASS` or `FAIL` and, when failing, `notes` giving the revision reason (notes are required on a `FAIL`). Recording a verdict creates a `QCReview` — an immutable record carrying the `milestone_id`, the `outcome`, and the `notes` — and is only permitted while the milestone is in `SUBMITTED`; otherwise it is refused with `ERR_MILESTONE_NOT_SUBMITTED`. QC reviews can be read individually and listed by `milestone_id`.

A `PASS` moves the milestone `SUBMITTED → APPROVED` and bumps the milestone's version. When the approved milestone is a `FULL` deliverable, its declared `finished_hours` is copied onto the title's `finished_hours`, and if the governing contract is a `PER_HOUR` deal, the narrator's one-time production fee is credited to `payout_balance_cents` at this moment (see §3.7 for the fee formula).

A `FAIL` sends the milestone into the revision loop. Each `FAIL` increments the milestone's `revision_count` by one and records the failing review. The milestone tolerates up to `MAX_REVISIONS` = 3 revision rounds: while the current `revision_count` is below `MAX_REVISIONS`, a `FAIL` moves the milestone `SUBMITTED → REVISION_REQUESTED`; but when `revision_count` has already reached `MAX_REVISIONS`, the next `FAIL` instead moves the milestone `SUBMITTED → REJECTED`, a terminal state reached after the fourth failing review. In either branch, when the failed milestone is a `FULL` deliverable, the title is walked back `IN_QC → IN_PRODUCTION` so the narrator can rework it.

After a revision request, the narrator resubmits by supplying a fresh `audio_url`. Resubmitting is only allowed while the milestone is in `REVISION_REQUESTED` — otherwise `ERR_MILESTONE_NOT_REVISABLE` — and only by the contract's narrator; it moves the milestone `REVISION_REQUESTED → SUBMITTED`, updates the stored `audio_url`, and bumps the milestone's version. When the milestone is a `FULL` deliverable, resubmission drives the title `IN_PRODUCTION → IN_QC` again, re-entering quality control for another review cycle.

### 3.6. Publication and Retail Distribution

Once the title's `FULL` milestone is `APPROVED`, the platform operator publishes the title, advancing it `IN_QC → PUBLISHED` and bumping its version. Publication requires that the title is in `IN_QC` — otherwise `ERR_TITLE_NOT_IN_QC` — and that the `FULL` milestone for the title's accepted contract has reached `APPROVED`; when no such `APPROVED` `FULL` milestone exists, publication is refused with `ERR_INVALID_STATE`. As a side effect of publication, every `ACTIVE` production booking for the title is completed, moving each `ACTIVE → COMPLETED` and releasing its booked days as described in §3.4. Publication is an operator action, so the ownership restriction that normally binds title mutations to the author does not apply.

Before titles can be sold, the operator registers retail distribution channels. A channel records a `name` (the retailer's display name, such as Audible or Apple), a `supported_territories` array whose members are each one of `WORLD`, `US`, `UK`, or `EU`, and a `retailer_cut_pct` — the fraction of gross the retailer keeps, which must be at least 0 and strictly less than 1. The net remitted to the rights holder on any sale through that channel is the gross multiplied by one minus `retailer_cut_pct`.

The operator lists a published title on a channel for a territory over a window. A listing records the `title_id`, the `channel_id`, the `territory` it sells into, and an `effective_from` and `effective_until` date pair; the window is a closed interval `[effective_from, effective_until]` with both ends inclusive. Listing requires the title to be in `PUBLISHED`; a listing against a title that is not published is refused with `ERR_TITLE_NOT_PUBLISHED`. The chosen `territory` must be served by the channel — it must appear in the channel's `supported_territories` — and must also fall within the title's own granted `territory`: a title granted `WORLD` may be listed into any territory, whereas a title granted a specific region (`US`, `UK`, or `EU`) may only be listed into that same region. A territory that the channel does not serve, or that lies outside the title's grant, is rejected with `ERR_TERRITORY_NOT_SUPPORTED`. The dates must be ordered, `effective_from` no later than `effective_until`, or the listing is rejected with `ERR_INVALID_DATE_RANGE`. A new listing begins in `ACTIVE` status.

Successive listings of the same title on the same channel must not crowd each other: a new listing is only accepted if its `effective_from` is strictly later than the latest `effective_until` among the existing non-`WITHDRAWN` listings on that same title-and-channel pair, plus a mandatory buffer of `DISTRIBUTION_GAP_DAYS`, which is 1 day. In other words, with a prior listing ending 2026-05-31, the earliest allowed next `effective_from` is 2026-06-02. A listing that violates this buffer gap is rejected with `ERR_LISTING_GAP_CONFLICT`. Listings can be listed and filtered by `title_id`, by `channel_id`, and by `status`. The operator withdraws an `ACTIVE` listing, moving it `ACTIVE → WITHDRAWN`; a withdraw attempt on a listing that is not `ACTIVE` is refused with `ERR_LISTING_NOT_ACTIVE`. A manual withdrawal, taken while the title's rights are still `ACTIVE`, does not freeze any royalty statements — that freezing happens only within the rights-reversion cascade of §3.8.

### 3.7. Sales and the Royalty Split

The operator records sales against an active listing. A sales event carries the `listing_id`, the `units_sold` in the event (zero or more), the `units_returned` (which defaults to 0 and may not be negative nor exceed `units_sold`), the `unit_price_cents` charged per unit (strictly greater than zero), and an `occurred_at` timestamp marking when the sale happened. A sales event may only be recorded against a listing in `ACTIVE` status, or it is refused with `ERR_LISTING_NOT_ACTIVE`. Sales events are immutable once written and can be listed and filtered by `listing_id`. The `occurred_at` value is used to window sales into accounting periods.

A royalty statement accounts for one title over a period. Creating a statement records the `title_id`, the `period_start`, and the `period_end`, and produces the statement in `PROVISIONAL` status; a statement may only be created while the title's rights are `ACTIVE`. At creation the statement's monetary fields are computed under the **provisional variant**, and the effective narrator share is captured into `narrator_share_pct_applied`. Statements can be listed and filtered by `title_id` and by `status`.

**Effective narrator share.** For a `PER_HOUR` contract the effective narrator share is 0 — per-hour narrators earn no royalty percentage — and `narrator_share_pct_applied` is 0. For a `ROYALTY_SHARE` contract the share is built from three factors. The base is the contract's `royalty_share_pct`. An exclusivity bonus of 0.05 is added when the title's `exclusivity` is `EXCLUSIVE`, and 0 is added otherwise. A tier multiplier is then chosen from the title's lifetime cumulative units — the sum of `units_sold` across every sales event on every listing of the title, regardless of period: the multiplier is 1.00 when cumulative units are below `TIER1_UNITS` (1,000 units), 1.10 when cumulative units are at least 1,000 but below `TIER2_UNITS` (5,000 units), and 1.20 when cumulative units are 5,000 or more. The effective share is the base plus bonus, multiplied by the tier multiplier, but capped at `SHARE_CAP` of 0.50 — that is, the smaller of 0.50 and the multiplied value. The share is a ratio carried at full precision; only the derived cent amounts are rounded.

**The split.** The statement includes the sales events whose listing belongs to the title and whose `occurred_at` falls within the closed period window — at or after `period_start` and at or before `period_end`. Those events are processed in a pinned order: ascending by `occurred_at`, and where two events share the same instant, ascending by `created_at`. For each event, a line quantity is determined by the variant: under the provisional variant the line quantity is `units_sold`; under the final variant it is `units_sold` minus `units_returned`. Each event's line gross is its line quantity multiplied by `unit_price_cents`, and these line grosses are summed into `gross_sales_cents`. The line net is the line gross multiplied by one minus the channel's `retailer_cut_pct`, rounded half up to whole cents, and it is this per-line rounded net that is accumulated into `statement_net_cents` — rounding each line before summing, never summing then rounding. The narrator's cut, `narrator_royalty_cents`, is `statement_net_cents` multiplied by `narrator_share_pct_applied`, rounded half up to whole cents. The author's cut, `author_royalty_cents`, is `statement_net_cents` minus `narrator_royalty_cents`, so the two cuts always partition the net exactly.

### 3.8. Finalization, Payout, Reversal, and Rights Reversion

After the return window closes, the operator finalizes a provisional statement, moving it `PROVISIONAL → FINALIZED` and bumping its version. Finalization requires the statement to be in `PROVISIONAL`, or it is refused with `ERR_STATEMENT_NOT_PROVISIONAL`. Finalizing recomputes every monetary field under the **final variant**, in which each line quantity is `units_sold` minus `units_returned` — returns are now deducted — and sets `variant` to `FINAL`. Because returns are subtracted, the finalized author and narrator royalties are typically smaller than their provisional figures.

The operator then pays a finalized statement, moving it `FINALIZED → PAID` and bumping its version. Paying requires the statement to be in `FINALIZED`, or it is refused with `ERR_STATEMENT_NOT_FINALIZED`, and there must be something to distribute: if the sum of `narrator_royalty_cents` and `author_royalty_cents` is not greater than zero, the payment is refused with `ERR_NOTHING_TO_PAY`. On payment, the author's `payout_balance_cents` is increased by that statement's `author_royalty_cents`, and the narrator's `payout_balance_cents` is increased by that statement's `narrator_royalty_cents` (which is 0 for a `PER_HOUR` title, whose narrator was compensated at approval instead).

**Narrator compensation across the two deal models.** A `PER_HOUR` narrator is paid a one-time production fee, independent of any sales, when the `FULL` milestone passes quality control: the fee is the title's `finished_hours` multiplied by the contract's `per_hour_rate_cents`, rounded half up to whole cents, and it is credited to the narrator's `payout_balance_cents` at that approval moment. A `ROYALTY_SHARE` narrator is instead paid per statement: the narrator earns the statement's `narrator_royalty_cents` when that statement is paid. The same finished production therefore yields a different narrator total under the two models — a flat per-hour fee versus an accumulation of royalty shares.

**Balances as a ledger.** An author's `payout_balance_cents` equals the sum of `author_royalty_cents` over that author's statements in `PAID` status; a narrator's `payout_balance_cents` equals the sum of per-hour production fees for that narrator's approved `PER_HOUR` full milestones plus the sum of `narrator_royalty_cents` over that narrator's `PAID` statements. Reversed statements are excluded from these sums. Because credited and debited amounts are the identical stored integer cents, the ledger never drifts. The operator may reverse a paid statement, moving it `PAID → REVERSED` and bumping its version; reversal requires the statement to be in `PAID`, or it is refused with `ERR_STATEMENT_NOT_PAID`. Reversal debits the author's `payout_balance_cents` by exactly the `author_royalty_cents` previously credited and debits the narrator's `payout_balance_cents` by exactly the `narrator_royalty_cents` previously credited, leaving the total distributed unchanged.

**Rights reversion and its cascade.** The rights holder may revert distribution rights on a published title, moving it `PUBLISHED → REVERTED`. Reverting requires that the caller owns the title, that the title is currently `PUBLISHED` — a revert on a non-published title is refused with `ERR_TITLE_NOT_REVERTABLE` — and that its `rights_status` is still `ACTIVE`. Reversion is the root of a consistency cascade that bumps the version of every entity it touches. It sets the title's `rights_status` to `REVERTED`. The title's `ACCEPTED` contract is terminated, moving it `ACCEPTED → TERMINATED`. Every `ACTIVE` distribution listing for the title is withdrawn, moving each `ACTIVE → WITHDRAWN`. And every royalty statement for the title that is still open — in `PROVISIONAL` or `FINALIZED` status — is frozen, moving `PROVISIONAL → FROZEN` or `FINALIZED → FROZEN` respectively, so that no further money moves on a title whose rights have been surrendered. After reversion, any production or distribution mutation on the title is refused with `ERR_RIGHTS_REVERTED`.

## 4. Endpoint Definitions

The endpoints below use standard status codes: an endpoint that creates a new resource returns 201, while an endpoint that reads or modifies an existing resource returns 200. Request and response payloads are not repeated here; the fields each operation consumes and the side effects it triggers are described in the §3 workflows. The table lists only the method, path, a short description, and the roles authorized to call it.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/authors` | Onboard an author (rights holder) | PlatformAdmin |
| POST | `/narrators` | Onboard a narrator | PlatformAdmin |
| GET | `/narrators/{id}` | Read a narrator | PlatformAdmin, Narrator, Author |
| GET | `/authors/{id}` | Read an author | PlatformAdmin, Author |
| POST | `/titles` | Create a title | Author |
| GET | `/titles/{id}` | Read a title | Author, Narrator, PlatformAdmin |
| GET | `/titles` | List titles (filter by author, status) | Author, PlatformAdmin |
| POST | `/titles/{id}/open` | Open a draft title for auditions | Author |
| POST | `/titles/{id}/retail-sample` | Set the retail sample clip window | Author |
| POST | `/titles/{id}/publish` | Publish a title whose full milestone is approved | PlatformAdmin |
| POST | `/titles/{id}/revert-rights` | Revert distribution rights on a published title | Author |
| POST | `/auditions` | Submit an audition for an open title | Narrator |
| GET | `/auditions/{id}` | Read an audition | Author, Narrator, PlatformAdmin |
| GET | `/auditions` | List auditions (filter by title, narrator, status) | Author, Narrator, PlatformAdmin |
| POST | `/auditions/{id}/decision` | Accept or decline an audition | Author |
| POST | `/contracts` | Offer a contract to an accepted narrator | Author |
| GET | `/contracts/{id}` | Read a contract | Author, Narrator, PlatformAdmin |
| GET | `/contracts` | List contracts (filter by title, narrator, status) | Author, Narrator, PlatformAdmin |
| POST | `/contracts/{id}/respond` | Accept or decline an offered contract | Narrator |
| POST | `/production-bookings` | Reserve a production window | Narrator |
| GET | `/production-bookings/{id}` | Read a booking | Narrator, PlatformAdmin |
| GET | `/production-bookings` | List bookings (filter by narrator, title, status) | Narrator, PlatformAdmin |
| POST | `/production-bookings/{id}/cancel` | Cancel an active booking | Narrator |
| POST | `/production-milestones` | Submit a milestone deliverable | Narrator |
| GET | `/production-milestones/{id}` | Read a milestone | Narrator, Author, QCReviewer, PlatformAdmin |
| GET | `/production-milestones` | List milestones (filter by contract, status) | Narrator, Author, QCReviewer, PlatformAdmin |
| POST | `/production-milestones/{id}/resubmit` | Resubmit after a revision request | Narrator |
| POST | `/production-milestones/{id}/qc-reviews` | Record a PASS or FAIL review | QCReviewer |
| GET | `/qc-reviews/{id}` | Read a QC review | QCReviewer, Author, PlatformAdmin |
| GET | `/qc-reviews` | List QC reviews (filter by milestone) | QCReviewer, Author, PlatformAdmin |
| POST | `/distribution-channels` | Register a retail distribution channel | PlatformAdmin |
| GET | `/distribution-channels/{id}` | Read a channel | PlatformAdmin, Author |
| POST | `/distribution-listings` | List a published title on a channel | PlatformAdmin |
| GET | `/distribution-listings/{id}` | Read a listing | PlatformAdmin, Author |
| GET | `/distribution-listings` | List listings (filter by title, channel, status) | PlatformAdmin, Author |
| POST | `/distribution-listings/{id}/withdraw` | Withdraw an active listing | PlatformAdmin |
| POST | `/sales-events` | Record a sales event against an active listing | PlatformAdmin |
| GET | `/sales-events/{id}` | Read a sales event | PlatformAdmin |
| GET | `/sales-events` | List sales events (filter by listing) | PlatformAdmin, Author |
| POST | `/royalty-statements` | Generate a provisional royalty statement | PlatformAdmin |
| GET | `/royalty-statements/{id}` | Read a royalty statement | PlatformAdmin, Author, Narrator |
| GET | `/royalty-statements` | List statements (filter by title, status) | PlatformAdmin, Author, Narrator |
| POST | `/royalty-statements/{id}/finalize` | Finalize a provisional statement | PlatformAdmin |
| POST | `/royalty-statements/{id}/pay` | Pay a finalized statement | PlatformAdmin |
| POST | `/royalty-statements/{id}/reverse` | Reverse a paid statement | PlatformAdmin |
| POST | `/_clock/set_current_utc` | Set the server logical clock (test harness) | PlatformAdmin |

## 5. Error Code Catalogue

The trigger conditions for these errors are described in the §2 and §3 narratives; the table records only the error identifier and its HTTP status.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_UNAUTHORIZED` | 403 |
| `ERR_VALIDATION` | 400 |
| `ERR_AUTHOR_NOT_FOUND` | 404 |
| `ERR_NARRATOR_NOT_FOUND` | 404 |
| `ERR_TITLE_NOT_FOUND` | 404 |
| `ERR_AUDITION_NOT_FOUND` | 404 |
| `ERR_CONTRACT_NOT_FOUND` | 404 |
| `ERR_BOOKING_NOT_FOUND` | 404 |
| `ERR_MILESTONE_NOT_FOUND` | 404 |
| `ERR_CHANNEL_NOT_FOUND` | 404 |
| `ERR_LISTING_NOT_FOUND` | 404 |
| `ERR_STATEMENT_NOT_FOUND` | 404 |
| `ERR_RESOURCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_RIGHTS_REVERTED` | 409 |
| `ERR_TITLE_NOT_OPEN` | 409 |
| `ERR_TITLE_NOT_IN_QC` | 409 |
| `ERR_TITLE_NOT_PUBLISHED` | 409 |
| `ERR_TITLE_NOT_REVERTABLE` | 409 |
| `ERR_AUDITION_NOT_SUBMITTED` | 409 |
| `ERR_AUDITION_NOT_ACCEPTED` | 409 |
| `ERR_CONTRACT_NOT_OFFERED` | 409 |
| `ERR_CONTRACT_NOT_ACCEPTED` | 409 |
| `ERR_DEAL_TYPE_FIELDS` | 422 |
| `ERR_MILESTONE_NOT_SUBMITTED` | 409 |
| `ERR_MILESTONE_NOT_REVISABLE` | 409 |
| `ERR_INVALID_FINISHED_HOURS` | 422 |
| `ERR_INVALID_DATE_RANGE` | 422 |
| `ERR_SAMPLE_TOO_LONG` | 422 |
| `ERR_TERRITORY_NOT_SUPPORTED` | 409 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_LISTING_GAP_CONFLICT` | 409 |
| `ERR_LISTING_NOT_ACTIVE` | 409 |
| `ERR_STATEMENT_NOT_PROVISIONAL` | 409 |
| `ERR_STATEMENT_NOT_FINALIZED` | 409 |
| `ERR_STATEMENT_NOT_PAID` | 409 |
| `ERR_NOTHING_TO_PAY` | 402 |
| `ERR_STALE_TITLE_VERSION` | 412 |
