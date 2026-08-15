# Voiceover Casting API — Product Requirements Document

## 1. Introduction

A voiceover talent agency sits between three parties who rarely share the same clock: brands that need a voice, artists who record auditions between other gigs, and studios whose rooms are booked in fifteen-minute increments. The work begins with an audition brief and ends, weeks later, with a delivered audio file, a usage buyout, an agency commission, and a talent payout. Along the way the agency must enforce union-rate pricing discipline, honor product-category exclusivity (a talent voicing one automaker's campaign cannot simultaneously voice a competitor's), keep studio calendars collision-free, and give the client a bounded window to request revisions after delivery.

This document specifies the API for the agency's casting and session-booking platform. It covers the full lifecycle: roster and client registration, project drafting, self-audition intake, casting selection with buyout pricing, exclusivity conflict tracking, studio session scheduling with remote directed-patch support, delivery with a fixed revision window, and invoice settlement. Because casting decisions, session completion, exclusivity expiry, and revision deadlines are all time-gated, the platform maintains its own logical clock rather than relying on wall-clock time; every temporal rule in this document is evaluated against that clock.

All endpoints are mounted under `/api`. The document is organized as follows: Section 2 defines system-wide contracts (authentication, response envelope, pagination, identity, clock, money, concurrency, validation ordering); Section 3 walks the business workflows in narrative form; Section 4 summarizes the endpoint surface; Section 5 catalogs the error codes.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, identifying the capacity in which that user acts. A request missing either header, or presenting a role the platform does not recognize, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). The single exception is the clock-advance operation used by operations staff, which is exempt from the header-presence requirement. A request whose role is recognized but not permitted for the attempted operation is rejected with `ERR_UNAUTHORIZED` (HTTP 403); this role check applies to every endpoint.

Six roles exist, spelled exactly as follows:

- `CastingDirector` — the agency casting director, who manages the talent roster, client accounts, studios, sessions, and casting opens. When `X-User-Role` is `CastingDirector`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `Client` — the brand or agency client who owns projects, selects talent, and accepts deliveries. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client` record; ownership checks on any resource that references a client (such as a project's `client_id`) compare that foreign-key field to `X-User-ID`.
- `Talent` — the voiceover artist, who submits self-auditions. When `X-User-Role` is `Talent`, `X-User-ID` is the `id` of the acting `Talent` record; ownership checks on any resource that references a talent (such as an audition's `talent_id`) compare that foreign-key field to `X-User-ID`.
- `StudioEngineer` — the studio operator, who marks sessions completed and delivers final files. When `X-User-Role` is `StudioEngineer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `Agent` — the agency finance representative, who issues and settles invoices. When `X-User-Role` is `Agent`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.
- `PlatformAdmin` — the platform operator, whose only capability is advancing the logical clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity.

Wherever an operation is ownership-scoped — a client acting on their own project, a talent submitting their own audition — an entity-backed role whose `X-User-ID` does not match the resource's owner foreign key is rejected with `ERR_FORBIDDEN` (HTTP 403).

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

List endpoints accept two query parameters: `limit`, defaulting to 10, with a minimum of 1 and a maximum of 100; and `offset`, defaulting to 0. Results are always sorted by `created_at` in ascending order. The `meta` block of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`, the last indicating whether additional results exist beyond the returned page.

### 2.4. Resource Identity and Common Properties

Every persisted resource exposes an `id`, minted by the server as a UUID with no type prefix. Resources additionally carry `created_at` and `updated_at`, both ISO 8601 UTC timestamps rendered with three fractional digits, and a `version`, an integer beginning at 1 on creation and incrementing by one on every mutation of the resource. Two resources deviate from this common shape: a `Delivery` and the `ClockState` carry only `id` and `created_at`; both `updated_at` and `version` are absent from them.

### 2.5. The Logical Clock

Time inside the platform is governed by a single logical clock exposed as the `ClockState` resource with one field, `current_utc`. At startup the clock reads exactly 2026-08-01T00:00:00Z and it must never fall back to wall-clock time. The clock advances only through the `PlatformAdmin`-only clock-advance capability, which accepts a target instant `to_iso8601`; the supplied instant must be strictly monotonically increasing relative to the current value, so the clock can never move backward.

Advancing the clock has one immediate housekeeping effect: any `ACTIVE` conflict exclusion whose `ends_at` is at or before the new clock value is lazily expired. All server-side timestamps written by the platform — an audition's `submitted_at`, a delivery's `delivered_at`, an invoice's `issued_at` — are taken from this logical clock, and every temporal precondition in Section 3 is evaluated against it.

### 2.6. Monetary Amounts, Precision, and Rounding

All monetary values are represented as integer cents; no fractional cents ever appear in a request or response. Wherever a calculation produces a non-integer intermediate, the result is rounded half-up to the nearest integer cent. The final buyout computation applies this rounding per line item and then sums the rounded line items — the per-line-then-sum order is part of the contract and is described fully in Section 3.4. A client account declares a `default_currency` of `USD`, `EUR`, or `GBP`, but amounts themselves are always bare integer cent values.

### 2.7. Optimistic Concurrency Control

Two write operations participate in optimistic concurrency control, and they are the only endpoints that accept a version field.

Updating a talent roster entry requires the request to carry `expected_talent_version`, holding the talent's `version` as the client last observed it. If another writer has advanced the talent's version since that read, the update is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting a roster entry it has not observed — for example, a concurrent fee change.

Cancelling a project requires the request to carry `expected_project_version`, holding the project's `version` as the client last observed it. If the project's version has advanced since that read — for example because a session was confirmed in the meantime — the cancellation is rejected with `ERR_STALE_VERSION` (HTTP 412).

Endpoints not named in this subsection do not take a version field.

### 2.8. Nested Resources and Path Resolution

Several resources live beneath a parent in the URL hierarchy — auditions, sessions, usage terms, deliveries, and invoices beneath a project; conflict exclusions beneath a talent. On any request, referenced resources are validated for existence in a fixed order: path identifiers first, evaluated left to right along the URL, then foreign keys carried in the request body. Any identifier that does not resolve to an existing resource produces `ERR_NOT_FOUND` (HTTP 404). Only after every reference resolves does the server evaluate ownership, state, and business rules.

### 2.9. Time Windows and Half-Open Interval Semantics

Three distinct time-window concepts recur across the platform, and all three use half-open intervals.

A session occupies the interval from `start_at` up to but not including `end_at`, where `end_at` is derived server-side as `start_at` plus `duration_minutes` minutes. Two sessions collide when the first session's start is strictly before the second session's end and the second session's start is strictly before the first session's end. Adjacency is not a collision: when one session's `end_at` equals another's `start_at`, both may stand — the buffer between sessions is zero. The collision rule is evaluated independently per studio and per talent, and only against sessions in `CONFIRMED` status.

An exclusivity window on a conflict exclusion runs from `starts_at` up to but not including `ends_at`. A revision window on a delivery closes at `revision_window_closes_at`, and its closing boundary is inclusive in the client's favor: a revision request arriving at exactly that instant is still accepted, because the rule is that a request is accepted whenever the clock is less than or equal to `revision_window_closes_at`.

### 2.10. Validation Order of Evaluation

When a request violates several rules at once, the checks fire in a fixed priority order so that earlier failures mask later ones. The order is: first the authentication-header check (`ERR_UNAUTHENTICATED`); then the role-permission check (`ERR_UNAUTHORIZED`); then existence of every referenced resource, path identifiers left to right before body foreign keys (`ERR_NOT_FOUND`); then ownership (`ERR_FORBIDDEN`); then whether the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); then temporal preconditions (`ERR_TEMPORAL_VIOLATION`); then the talent exclusivity-conflict check (`ERR_TALENT_CONFLICT`); then the session-overlap check (`ERR_SESSION_OVERLAP`); then the directed-patch capability check (`ERR_PATCH_NOT_SUPPORTED`); then uniqueness (`ERR_DUPLICATE`); then enum and shape validity (`ERR_INVALID_REQUEST`); then the pickup/retake prerequisite (`ERR_PICKUP_PREREQUISITE`); and finally fiscal validity (`ERR_FISCAL_INVALID`). Because of this ordering, a request that fails both an earlier and a later check always surfaces the earlier error.

## 3. Business Logic & Workflows

### 3.1. Building the Roster: Talents, Clients, and Studios

Before any project can be cast, the agency populates three registries, all maintained by a `CastingDirector`.

Registering a talent captures the artist's `stage_name`, a contact `email`, the `voice_profile` classification (one of `MALE_DEEP`, `MALE_LIGHT`, `FEMALE_DEEP`, `FEMALE_LIGHT`, `NONBINARY`, or `CHILD`), the `languages` the artist records in as a list of ISO 639-1 codes, the artist's `union_status` (`UNION`, `NON_UNION`, or `FICORE`), and `base_session_fee_cents`, the artist's fee for a one-hour session before any usage multipliers are applied. The new roster entry begins with `roster_status` set to `ACTIVE`; the other two roster states, `SUSPENDED` and `OFFBOARDED`, are reached only through later roster updates. Each talent's `email` must be unique across the roster, and a duplicate registration is rejected with `ERR_DUPLICATE` (HTTP 409). The talent record also exposes `active_conflict_categories`, a computed array described in Section 3.5 that reflects the artist's live exclusivity commitments.

A roster entry can later be updated — a new `stage_name`, a revised `base_session_fee_cents`, or a changed `roster_status` — by a `CastingDirector`. Because roster entries are shared working state, the update is concurrency-guarded: it must carry `expected_talent_version` matching the talent's current `version`, and a stale value is rejected with `ERR_STALE_VERSION` as described in Section 2.7. A successful update increments the talent's `version` by one. The roster can be browsed through the talent list, which supports filtering by `voice_profile`, `union_status`, and `roster_status`, and is visible to casting directors and clients.

Registering a client captures the `company_name`, a unique `contact_email` (duplicates rejected with `ERR_DUPLICATE`), the `billing_email` that receives invoices, and an optional `default_currency` of `USD`, `EUR`, or `GBP` that defaults to `USD` when omitted. A new client account starts with `account_status` set to `ACTIVE`, the alternative being `SUSPENDED`.

Registering a studio captures its `studio_name`, a free-text `location` describing city and room, whether it `has_directed_patch` for remote direction over Source-Connect or ISDN, its `hourly_rate_cents`, and its `operating_tz` as an IANA timezone string such as America/Los_Angeles. A new studio opens with `status` set to `OPEN`; the only other studio state is `CLOSED`.

### 3.2. Drafting the Project and Opening Casting

A project begins when a `Client` creates it in `DRAFT` status. The creation payload names the owning client via `client_id` — which must equal the acting client's `X-User-ID`, failing which the request is rejected with `ERR_FORBIDDEN` — together with a `title`, the `product_category` the campaign belongs to (`AUTOMOTIVE`, `PHARMA`, `FAST_FOOD`, `FINANCE`, `TECH`, `RETAIL`, `ALCOHOL`, or `GAMING`), the `usage_type` (`BROADCAST`, `DIGITAL`, or `TERM`), the `spots_count` of distinct spots the buyout covers, the `brief_text` of direction notes and script excerpt, and the `audition_deadline`, an ISO 8601 UTC cutoff for self-audition submissions. When `usage_type` is `TERM`, `term_months` must be present and states the license duration in months; for any other usage type `term_months` must be absent and stays null. The `spots_count` must be at least 1. `exclusivity_required` is optional and defaults to false; when true, the cast talent must hold no live conflict in the project's category (Section 3.5). A payload violating these shape rules — an unrecognized enum member, a missing `term_months` on a `TERM` project, a `spots_count` below 1 — is rejected with `ERR_INVALID_REQUEST` (HTTP 400). The project record carries `selected_talent_id`, which stays null until casting completes, and the two computed buyout figures `buyout_quote_cents` and `buyout_final_cents`. Projects can be browsed through the project list, filterable by `client_id`, `selected_talent_id`, and `status`.

When the brief is ready, a `CastingDirector` opens casting, moving the project `DRAFT → CASTING`. Opening requires the `audition_deadline` to lie strictly after the current clock; a deadline already in the past is rejected with `ERR_TEMPORAL_VIOLATION` (HTTP 422). It also requires `brief_text` to be non-empty — a project without direction notes is not in a fit state to cast, and the transition is rejected with `ERR_INVALID_STATE` (HTTP 409).

Opening casting triggers the provisional buyout quote, stored on `buyout_quote_cents` and used for budgeting while talent is still unknown. The quote assumes union scale: a base of 65000 cents is multiplied by a usage multiplier — 2.50 for `BROADCAST`, 1.50 for `DIGITAL`, or, for `TERM`, 1.00 plus 0.10 for each month of `term_months` — and then by a spot multiplier of 1.00 plus 0.20 for every spot beyond the first (a single-spot project therefore carries no uplift). The product is rounded half-up to an integer number of cents. Because the quote assumes union scale rather than any particular artist's fee, it routinely differs from the final figure computed at cast time.

### 3.3. Self-Audition Intake and Shortlisting

While a project is in `CASTING`, talent submit self-auditions against it. A `Talent` submits with a payload naming `talent_id` — which must match the acting talent's `X-User-ID` or the submission is rejected with `ERR_FORBIDDEN` — along with `audio_file_url` pointing at the submitted MP3 or WAV file and an optional `slate_text` note that defaults to an empty string. Submission is only possible while the project is in `CASTING`; submitting against a project in any other state is rejected with `ERR_INVALID_STATE`. Each artist may audition at most once per project: a second submission for the same `(project_id, talent_id)` pair is rejected with `ERR_DUPLICATE`. The server stamps `submitted_at` from the logical clock, and the audition begins in `SUBMITTED` status. The audition's `project_id` ties it back to the casting project.

The client reviews the inbound auditions — the project-scoped list is visible to casting directors and the client, while the global audition list, filterable by `talent_id`, is also visible to talent reviewing their own submissions. Shortlisting moves an audition `SUBMITTED → SHORTLISTED`, and rejecting moves an audition from either `SUBMITTED` or `SHORTLISTED` to `REJECTED`. Both actions are `Client`-only, require the project to still be in `CASTING` (otherwise `ERR_INVALID_STATE`), and are ownership-scoped to the project's owning client (otherwise `ERR_FORBIDDEN`). `REJECTED` and `SELECTED` are the audition's terminal states.

### 3.4. Selecting Talent: Cast Confirmation, Buyout Finalization, and Usage Terms

Casting concludes when the owning `Client` selects one audition by passing its `self_audition_id`. The selection is heavily guarded. The audition must exist and belong to this project with a status of either `SUBMITTED` or `SHORTLISTED`; an unknown identifier yields `ERR_NOT_FOUND` and an audition in any other state yields `ERR_INVALID_STATE`. The acting client must own the project (`ERR_FORBIDDEN`). The chosen artist's `roster_status` must be `ACTIVE` — a suspended or offboarded artist cannot be cast, and the attempt is rejected with `ERR_INVALID_STATE`. When the project's `exclusivity_required` is true, the selected talent must hold no `ACTIVE` conflict exclusion in the project's `product_category` whose window overlaps the interval starting at the current clock and ending `term_months` months later; a live conflict is rejected with `ERR_TALENT_CONFLICT` (HTTP 409). Finally, the finalized buyout must come out positive: a transition that would produce a `buyout_final_cents` of zero or less is rejected with `ERR_FISCAL_INVALID` (HTTP 422).

A successful selection moves the project `CASTING → CAST` and fans out into a cascade of side effects. The chosen audition advances to `SELECTED`, while every sibling audition on the same project still sitting in `SUBMITTED` or `SHORTLISTED` is moved to `REJECTED`. The project records the chosen artist in `selected_talent_id`. The final buyout `buyout_final_cents` is computed now that the talent is known, in two line items whose rounding order matters: line one is the talent's `base_session_fee_cents` multiplied by the same usage multiplier used for the quote (2.50 for `BROADCAST`, 1.50 for `DIGITAL`, or 1.00 plus 0.10 per month of `term_months` for `TERM`) and by a union multiplier that is 1.00 for `UNION`, 1.00 for `FICORE`, and 0.85 for `NON_UNION`; line two is the incremental spot uplift, computed as line one multiplied by the spot multiplier minus 1.00, where the spot multiplier is 1.00 plus 0.20 for every spot beyond the first. Each line item is individually rounded half-up to integer cents, and the total is the sum of the two rounded line items.

The same transition creates the project's `UsageTerms` row, exactly one per project — any arrangement that would produce a second row is a uniqueness violation rejected with `ERR_DUPLICATE`. The row mirrors the project's `usage_type` and `term_months` (null for non-`TERM` projects), stores the computed `buyout_cents` equal to the final buyout, and splits that amount into the agency's `agent_commission_cents` and the artist's `talent_payout_cents`. The commission follows a volume-tier waterfall: under 500000 cents the agency takes 10 percent; from 500000 cents up to but not including 1500000 cents it takes 15 percent; at 1500000 cents and above it takes 20 percent. A `UNION` artist receives a two-percentage-point reduction on the applicable tier rate, subject to a floor of 5 percent. The commission amount itself is rounded half-up to integer cents, and the payout is the buyout minus the commission. The row's `locked_at_cast` flag is set to true at creation, after which the terms are immutable.

The usage terms also carry the placement detail: `broadcast_regions`, a list of region codes such as NA, EU, or APAC, which must be non-empty exactly when `usage_type` is `BROADCAST`; and `digital_placements`, a list such as PRE_ROLL, SOCIAL_PAID, or OLV, which is required exactly when `usage_type` is `DIGITAL`. The owning client may edit these placement lists — and only these — while `locked_at_cast` remains false; once the flag is set the terms are frozen and further edits are rejected with `ERR_INVALID_STATE`. A placement payload inconsistent with the project's usage type — for instance empty `broadcast_regions` on a `BROADCAST` project — is rejected with `ERR_FISCAL_INVALID`. Reading the terms returns an array of length zero or one, since the row exists only after casting.

Finally, when `exclusivity_required` is true, the selection also creates a conflict exclusion for the chosen talent in the project's `product_category`, running from the current clock until `term_months` months later, and refreshes the talent's `active_conflict_categories` accordingly (Section 3.5).

### 3.5. Exclusivity and Conflict Windows

A `ConflictExclusion` record binds a talent (via `talent_id`) to a `product_category` for the half-open window from `starts_at` up to but not including `ends_at`. Its `source` distinguishes exclusions that arose from casting (`PROJECT_CAST`, the default) from manually placed holds (`MANUAL_HOLD`). Every exclusion begins in `ACTIVE` status and ends in one of two terminal states: `RELEASED`, reached when a `CastingDirector` manually releases it or when the originating project is cancelled; and `EXPIRED`, reached when time runs out.

Expiry is lazy rather than scheduled. An `ACTIVE` exclusion whose `ends_at` is at or before the current clock is flipped to `EXPIRED` the next time it is read, the next time the clock advances past its end, and on every cast attempt that touches it. On either release or expiry, the affected `product_category` is removed from the talent's `active_conflict_categories` — but only if no other still-`ACTIVE` exclusion covers the same category.

The `active_conflict_categories` array on the talent record is therefore a pure derivation: it contains the distinct product categories of that talent's exclusions that are `ACTIVE` and whose window currently contains the clock (that is, `starts_at` is at or before the current time and `ends_at` is strictly after it), ordered ascending by `ends_at` with ties broken by ascending `created_at`. Casting directors, clients, the talent, and agents can all inspect an artist's exclusions through the talent-scoped listing or by fetching an individual exclusion.

### 3.6. Booking the Studio: Sessions, Patches, and Overlap Discipline

Once a project is in `CAST`, a `CastingDirector` schedules sessions under it. Creating a session against a project in any other state is rejected with `ERR_INVALID_STATE`. The creation payload supplies the `studio_id`, the `session_kind` (`PRIMARY` for the main booking, `PICKUP` for additional lines after scope expansion, or `RETAKE` for redo work after a revision request), whether the session runs `directed_patch` for remote direction, the `start_at` instant, and `duration_minutes`, which must be at least 15 — shorter bookings are rejected with `ERR_INVALID_REQUEST`. The server derives `end_at` as `start_at` plus `duration_minutes`, stamps the session's `talent_id` by denormalizing the project's `selected_talent_id` at booking time, and opens the session in `TENTATIVE` status.

Two capability checks guard creation. A session requesting `directed_patch` may only be placed in a studio whose `has_directed_patch` is true; otherwise creation is rejected with `ERR_PATCH_NOT_SUPPORTED` (HTTP 422). And the requested interval must not collide with any `CONFIRMED` session sharing the same studio or the same talent, under the half-open overlap rule of Section 2.9; a collision is rejected with `ERR_SESSION_OVERLAP` (HTTP 409). Firing in the Section 2.10 order — after the project-state check and before the directed-patch capability check — this creation-time overlap check is evaluated only when the requested interval can be derived from the payload, that is, when `start_at` parses as a valid ISO 8601 timestamp and `duration_minutes` is a non-negative integer; the derived interval is used even when `duration_minutes` would later fail the fifteen-minute minimum. When the interval cannot be derived, the overlap check is skipped and the directed-patch capability check and the shape rules fire in their usual order, so a payload with a malformed `start_at` or `duration_minutes` is governed by those later checks. Sessions attached to a project can be listed by casting directors, the client, the talent, and studio engineers, and the global session list can be filtered by `talent_id` and `studio_id`.

Confirmation moves a session `TENTATIVE → CONFIRMED` and is performed by a `CastingDirector`. The studio must still be `OPEN` (a closed studio rejects the confirm with `ERR_INVALID_STATE`), and the overlap check is re-evaluated at confirm time against the same per-studio and per-talent `CONFIRMED` sets, because the booking landscape may have changed since creation. Two kind-specific prerequisites also apply: confirming a `PICKUP` session requires the project to already have at least one `COMPLETED` `PRIMARY` session, and confirming a `RETAKE` session requires the project's delivery to have `revision_requested` set to true; either failure is rejected with `ERR_PICKUP_PREREQUISITE` (HTTP 422). When the confirmed session is the project's first `CONFIRMED` session and the project is in `CAST`, confirmation also advances the project `CAST → IN_SESSION`.

A session — whether still `TENTATIVE` or already `CONFIRMED` — is marked `COMPLETED` by a `StudioEngineer` once the clock has reached or passed its `end_at`; completing earlier is rejected with `ERR_TEMPORAL_VIOLATION`. Conversely, a `CastingDirector` may cancel a `TENTATIVE` or `CONFIRMED` session only while the clock is still strictly before its `start_at`; cancelling at or after the start is rejected with `ERR_TEMPORAL_VIOLATION`. Sessions may also be cancelled by the platform itself when the owning project is cancelled. `COMPLETED` and `CANCELLED` are the session's terminal states.

### 3.7. Session Fees: Provisional Quotes and Final Amounts

Session fees exist in two variants, and the two can legitimately produce different totals for an identical booking.

The provisional variant is quoted at booking time, while the session is `TENTATIVE`, and is used purely for budget display. The scheduled `duration_minutes` is rounded up to the next whole 15-minute block, the resulting block count is converted to hours, and the total is the studio's `hourly_rate_cents` multiplied by that hour figure. No patch surcharge applies to the provisional quote.

The final variant is computed when the session transitions to `COMPLETED`, using actual elapsed time rather than the scheduled duration. The elapsed minutes from `start_at` to the moment completion is recorded are rounded up to a 5-minute granularity, subject to a 15-minute minimum — a session that ran 12 minutes still bills 15. The billed minutes are converted to hours and multiplied by the studio's `hourly_rate_cents`. When the session ran with `directed_patch`, a 25 percent surcharge is applied to that amount and the result is rounded half-up to integer cents.

Completion also determines when the fee becomes an invoice. Completing a `PICKUP` session generates a `PICKUP_FEE` invoice in `PENDING` status immediately. Completing a `PRIMARY` or `RETAKE` session defers its `SESSION_FEE` invoice until the project is delivered, as described in the next subsection.

### 3.8. Delivery, the Revision Window, and Project Close-Out

When the work is in the can, a `StudioEngineer` delivers the final files by supplying the `session_id` whose audio is being delivered and the `file_url` of the final mix. Delivery requires the project to be in `IN_SESSION` (otherwise `ERR_INVALID_STATE`), at least one session on the project to be `COMPLETED`, and no `PICKUP` session on the project to still sit in `CONFIRMED` or `TENTATIVE` — outstanding pickup work blocks delivery, again with `ERR_INVALID_STATE`.

A successful delivery creates the `Delivery` record — one of the two resource kinds that carry only `id` and `created_at` per Section 2.4 — stamped with `delivered_at` from the logical clock and `revision_requested` initialized to false. The record's `revision_window_hours` is the constant 72, and `revision_window_closes_at` is derived as `delivered_at` plus 72 hours. The project's status advances `IN_SESSION → DELIVERED`, and delivery is the platform's invoicing moment: a `BUYOUT` invoice in `PENDING` status is generated referencing the usage terms' `buyout_cents`, and a `SESSION_FEE` invoice in `PENDING` status is generated for every `COMPLETED` `PRIMARY` or `RETAKE` session not yet invoiced. Deliveries can be listed per project or globally, the latter filterable by `session_id`.

From delivery, the project travels one of two roads. If the client wants changes, the owning `Client` requests a revision while the clock is less than or equal to `revision_window_closes_at` — a request at exactly the closing instant is still inside the window — and while `revision_requested` is still false. A request after the window closes is rejected with `ERR_TEMPORAL_VIOLATION`; a second request is rejected with `ERR_INVALID_STATE`. A granted revision sets `revision_requested` to true and reverts the project `DELIVERED → CAST`, opening a retake-and-pickup round: a `RETAKE` session may now be scheduled and confirmed, and a `PICKUP` session is allowed only if the scope expands.

Otherwise the project closes. The platform closes it automatically once the clock has moved strictly past `revision_window_closes_at` with `revision_requested` still false; the client may also close it explicitly at acceptance. Either path moves the project `DELIVERED → CLOSED` and issues every `PENDING` invoice on the project, stamping each `issued_at` with the clock. `CLOSED` is a terminal project state.

### 3.9. Invoices, Agency Settlement, and Cancellation Teardown

Every invoice is typed by `invoice_kind` — `BUYOUT`, `SESSION_FEE`, or `PICKUP_FEE` — and carries three amounts: `talent_amount_cents` payable to the artist, `agent_commission_cents` retained by the agency, and `total_cents`, which is exactly the sum of the other two. For the `BUYOUT` invoice these amounts come from the usage terms' computed payout and commission split. An invoice begins `PENDING`, becomes `ISSUED` either when an `Agent` issues it manually or when the project closes (which issues all pending invoices at once, stamping `issued_at` from the clock), and an `ISSUED` invoice is settled when an `Agent` marks it `PAID`. A `PENDING` invoice can also be voided — `VOID` is terminal and is reached when the owning project is cancelled. Invoices are readable per project or individually by casting directors, the client, the agent, and the talent.

Cancellation is the client's escape hatch, available only from `DRAFT`, `CASTING`, or `CAST`. The request must carry `expected_project_version` matching the project's current `version`; a stale value is rejected with `ERR_STALE_VERSION` per Section 2.7. Cancellation is refused with `ERR_INVALID_STATE` when any session on the project is `CONFIRMED`, or when any invoice has already reached `ISSUED` or `PAID`. A successful cancellation moves the project to the terminal `CANCELLED` state, increments its `version` by one, and tears down its dependents in one cascade: every audition still in `SUBMITTED` or `SHORTLISTED` moves to `REJECTED`; every `TENTATIVE` session moves to `CANCELLED`; every `ACTIVE` conflict exclusion created by this project is `RELEASED` (with `active_conflict_categories` refreshed as in Section 3.5); and every `PENDING` invoice is voided.

## 4. Endpoint Definitions

Creation of a new resource returns HTTP 201; all other successful operations, including reads, state transitions, and modifications, return HTTP 200. Request payloads, side effects, and preconditions for each endpoint are as specified narratively in Sections 2 and 3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock (monotonic; startup default 2026-08-01T00:00:00Z) | PlatformAdmin |
| POST | /api/talents | Register a new talent | CastingDirector |
| GET | /api/talents | List talents, filterable by voice_profile, union_status, roster_status | CastingDirector, Client |
| GET | /api/talents/{id} | Get a talent | CastingDirector, Client, Talent, Agent |
| PUT | /api/talents/{id} | Update a roster entry (optimistic concurrency via expected_talent_version) | CastingDirector |
| GET | /api/talents/{id}/conflict_exclusions | List conflict exclusions for a talent | CastingDirector, Client, Talent, Agent |
| POST | /api/clients | Register a client | CastingDirector |
| GET | /api/clients/{id} | Get a client | CastingDirector, Client, Agent |
| POST | /api/projects | Create a project in DRAFT | Client |
| GET | /api/projects | List projects, filterable by client_id, selected_talent_id, status | CastingDirector, Client, Agent |
| GET | /api/projects/{id} | Get a project | CastingDirector, Client, Talent, Agent |
| POST | /api/projects/{id}/open_casting | Open casting (DRAFT → CASTING); computes the provisional buyout quote | CastingDirector |
| POST | /api/projects/{id}/select_talent | Select an audition and cast the project (CASTING → CAST) | Client |
| POST | /api/projects/{id}/cancel | Cancel a project (optimistic concurrency via expected_project_version) | Client |
| POST | /api/projects/{id}/close | Accept delivery and close the project (DELIVERED → CLOSED) | Client |
| POST | /api/projects/{id}/request_revision | Request a revision within the revision window (DELIVERED → CAST) | Client |
| POST | /api/projects/{id}/self_auditions | Submit a self-audition for the project | Talent |
| GET | /api/projects/{id}/self_auditions | List auditions for a project | CastingDirector, Client |
| GET | /api/self_auditions | List auditions, filterable by talent_id | CastingDirector, Client, Talent |
| GET | /api/self_auditions/{id} | Get an audition | CastingDirector, Client, Talent |
| POST | /api/self_auditions/{id}/shortlist | Shortlist an audition | Client |
| POST | /api/self_auditions/{id}/reject | Reject an audition | Client |
| POST | /api/studios | Register a studio | CastingDirector |
| GET | /api/studios/{id} | Get a studio | CastingDirector, Client, StudioEngineer |
| POST | /api/projects/{id}/sessions | Create a session (TENTATIVE) | CastingDirector |
| GET | /api/projects/{id}/sessions | List sessions for a project | CastingDirector, Client, Talent, StudioEngineer |
| GET | /api/sessions | List sessions, filterable by talent_id and studio_id | CastingDirector, Client, Talent, StudioEngineer |
| GET | /api/sessions/{id} | Get a session | CastingDirector, Client, Talent, StudioEngineer |
| POST | /api/sessions/{id}/confirm | Confirm a tentative session; may advance the project to IN_SESSION | CastingDirector |
| POST | /api/sessions/{id}/complete | Mark a session completed after its end | StudioEngineer |
| POST | /api/sessions/{id}/cancel | Cancel a session before its start | CastingDirector |
| GET | /api/projects/{id}/usage_terms | Get the project's usage terms (array of zero or one) | CastingDirector, Client, Agent |
| PUT | /api/projects/{id}/usage_terms | Edit usage-term placements before the terms lock at cast | Client |
| POST | /api/projects/{id}/deliveries | Deliver final files; advances the project to DELIVERED | StudioEngineer |
| GET | /api/projects/{id}/deliveries | List deliveries for a project | CastingDirector, Client, StudioEngineer |
| GET | /api/deliveries | List deliveries, filterable by session_id | CastingDirector, Client, StudioEngineer |
| GET | /api/deliveries/{id} | Get a delivery | CastingDirector, Client, StudioEngineer |
| GET | /api/projects/{id}/invoices | List invoices for a project | CastingDirector, Client, Agent, Talent |
| GET | /api/invoices/{id} | Get an invoice | CastingDirector, Client, Agent, Talent |
| POST | /api/invoices/{id}/issue | Issue a pending invoice | Agent |
| POST | /api/invoices/{id}/mark_paid | Mark an issued invoice as paid | Agent |
| GET | /api/conflict_exclusions/{id} | Get a conflict exclusion | CastingDirector, Client, Talent, Agent |
| POST | /api/conflict_exclusions/{id}/release | Manually release an active exclusion | CastingDirector |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_TEMPORAL_VIOLATION | 422 |
| ERR_TALENT_CONFLICT | 409 |
| ERR_SESSION_OVERLAP | 409 |
| ERR_PATCH_NOT_SUPPORTED | 422 |
| ERR_DUPLICATE | 409 |
| ERR_INVALID_REQUEST | 400 |
| ERR_PICKUP_PREREQUISITE | 422 |
| ERR_FISCAL_INVALID | 422 |
