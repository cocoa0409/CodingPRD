# Mastering Studio API — Product Requirements Document

## 1. Introduction

A mastering studio sells two things at once: scarce engineer hours and a guarantee that a finished record will survive the technical scrutiny of every distribution platform it ships to. This specification covers the Mastering Studio API, which orchestrates that business end to end — session booking with capacity-aware engineer assignment, source-file intake with technical QC, per-platform loudness and format targets, revision rounds governed by turnaround SLAs, deliverable generation in DDP, stem, and instrumental forms with ISRC/UPC metadata embedding and verification, and long-term archive with paid recall for later reuse. All resources are served under the `/studio` prefix.

The operating model rests on a deliberate segregation of duties: clients commission and approve work, engineers perform intake and mastering, an independent QA function judges every deliverable, and studio managers administer the roster, the pricing rules, and all overrides. Money moves at well-defined moments — a provisional quote is locked at booking time, and a final charge is computed and debited at client approval — with rush-tier multipliers, per-round revision billing, and SLA-breach surcharges reconciled into the final figure. All time-dependent behavior (hold expiries, revision deadlines, restores) is driven by a logical clock under studio-manager control rather than the wall clock, so every actor observes the same timeline.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting party, and `X-User-Role`, declaring one of four roles: `Client`, `Engineer`, `QAChecker`, and `StudioManager`. A request missing either header, presenting a malformed header, or declaring a role outside this list is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not permitted on the target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

Identity semantics differ by role, and they are contractual. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting Client record; ownership checks on any resource that references a Client compare the resource's foreign-key field — for a project, its `client_id` — to `X-User-ID`, and a client attempting to act on a project they do not own is rejected with `ERR_CLIENT_NOT_OWNER` (HTTP 403). A client may likewise fetch only their own Client record. On list endpoints the ownership rule is enforced as visibility scoping rather than rejection: a `Client` caller's results are restricted to resources attached to projects they own — session slots not yet attached to any project remain visible to every client — and the `meta` pagination counts reflect the scoped set. When `X-User-Role` is `Engineer`, `X-User-ID` is the `id` of the acting Engineer record; assignment checks on any resource that references an Engineer compare the project's `assigned_engineer_id` to `X-User-ID`, and an engineer attempting an action on a project assigned to a different engineer is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403). When `X-User-Role` is `QAChecker`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`. The same opaque treatment applies when `X-User-Role` is `StudioManager` — an opaque operator identifier that the server may record but never compares against an entity's `id`.

Segregation of duties is the point of the `QAChecker` role: the QA operator who judges a deliverable must never be the engineer who built it. Studio managers hold override and administrative powers — client lifecycle actions, credit adjustments, roster onboarding, platform and rush-tier configuration, QC waivers, slot cancellation, deliverable retirement, archive restores, metadata revocation, and control of the logical clock.

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

---

### 2.3. Pagination

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0. A non-integer `limit` or `offset`, a `limit` outside 1–100, or a negative `offset` is rejected with `ERR_INVALID_REQUEST` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order, with resources stamped in the same instant ordered by insertion sequence.

Paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties

Every primary resource in the system — Client, Engineer, PlatformProfile, Project, SessionSlot, SourceAsset, RevisionRound, Deliverable, QCReport, MetadataTag, ArchiveBundle, and RushTierRule — carries a standard set of system-managed fields:

- **`id` (string):** a unique, server-generated identifier for the resource, formatted as a UUID with no type prefix.
- **`created_at` (string):** an ISO 8601 timestamp in UTC with three fractional digits (for example, `2026-05-01T00:00:00.000Z`) recording when the resource was first created.
- **`updated_at` (string):** an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on every change to the resource's properties.
- **`version` (integer):** a system-managed integer that starts at 1 when the resource is created, increments with every mutation of the resource, and backs optimistic concurrency control.

Any mutation counts, including system-written recomputations: when a derived field such as `quoted_price_cents` or `final_price_cents` is written to a project, or when a cascade touches a parent record, the affected resource's `updated_at` refreshes and its `version` increments. Each transition described in §3 individually mutates the resource it names.

### 2.5. Guard Evaluation Order

Every request is evaluated against a fixed guard chain, and guards fire in ascending priority: a failure at an earlier step halts evaluation and masks every later check. Independently of this chain, a payload that is missing a required field or carries a malformed value or a value of the wrong type is rejected with `ERR_INVALID_REQUEST` (HTTP 400); a timestamp field that cannot be parsed as ISO-8601 is instead rejected with `ERR_INVALID_FORMAT` (HTTP 400).

The ordered chain is as follows. First (priority 1), authentication: the `X-User-Role` and `X-User-ID` headers must be present and the role must be one of the declared roles, on every endpoint, failing with `ERR_UNAUTHENTICATED` (HTTP 401). Second (priority 2), authorization: the acting role must be permitted for the endpoint, on every endpoint, failing with `ERR_UNAUTHORIZED` (HTTP 403). Third (priority 3), path existence: every resource identified by a path segment must exist, validated left to right, failing with `ERR_NOT_FOUND` (HTTP 404). Fourth (priority 4), body referential existence: every foreign key in a request body — `client_id`, `target_platform_profile_id`, `project_id`, and the like — must reference an existing row on any create or update call, failing with `ERR_NOT_FOUND` (HTTP 404). Fifth (priority 5), state admissibility: the resource's current state must permit the requested transition on every action endpoint, failing with `ERR_INVALID_STATE` (HTTP 409); an entity that has already reached a terminal state rejects further transitions with `ERR_ALREADY_TERMINAL` (HTTP 409). The terminal states are: Client `TERMINATED`; Project `CANCELLED`; SessionSlot `RELEASED`, `CONSUMED`, and `CANCELLED`; SourceAsset `PASSED` and `WAIVED`; RevisionRound `APPROVED`, `REJECTED`, and `EXPIRED`; Deliverable `RETIRED`; MetadataTag `VERIFIED` and `REVOKED`; ArchiveBundle `RESTORED` and `FAILED`. Ownership and assignment checks (`ERR_CLIENT_NOT_OWNER`, `ERR_ENGINEER_NOT_ASSIGNED`) sit outside the numbered chain: they run once the resources named in the path exist (after priority 3) and always before state admissibility (priority 5).

Sixth (priority 6), cross-entity activity guards: the engineer must be `AVAILABLE` before a session hold is confirmed, and the client must be `ACTIVE` before a project is booked — booking and hold-confirmation are the two guarded operations — failing with `ERR_ENTITY_NOT_ACTIVE` (HTTP 422). Seventh (priority 7), slot overlap: a requested slot must not overlap an existing `BOOKED` or `HELD` slot for the same engineer on slot creation and on booking, failing with `ERR_SLOT_CONFLICT` (HTTP 409). Eighth (priority 8), engineer capacity: the engineer's remaining capacity inside the requested window must cover the requested duration on booking, failing with `ERR_CAPACITY_EXCEEDED` (HTTP 422). Ninth (priority 9), time boundaries: `scheduled_start_at`, `slot_start_at`, and `slot_end_at` must land on a 30-minute boundary on project creation and slot creation, failing with `ERR_INVALID_TIME_BOUNDARY` (HTTP 400). Tenth (priority 10), source uniqueness: an uploaded asset's `sha256` must not already exist on the same project, failing with `ERR_DUPLICATE_ASSET` (HTTP 409).

Eleventh (priority 11), UPC uniqueness: a project's `upc`, when present, must be unique across all projects, on creation and on any update of an existing project, failing with `ERR_DUPLICATE_UPC` (HTTP 409). Twelfth (priority 12), code formats: ISRC and UPC values must match their format rules on project creation and on metadata embedding, failing with `ERR_INVALID_FORMAT` (HTTP 400). Thirteenth (priority 13), metadata consistency: an embedded tag's `upc` must equal the parent project's `upc` when the project has one, failing with `ERR_METADATA_MISMATCH` (HTTP 422). Fourteenth (priority 14), credit sufficiency: a debit must not drive the client's balance negative, on round approval and on archive recall, failing with `ERR_INSUFFICIENT_CREDIT` (HTTP 402). Fifteenth (priority 15), revision deadlines: a round submission must occur no later than its `deadline_at`, failing with `ERR_SLA_BREACH` (HTTP 422).

Sixteenth (priority 16), hold expiry: a hold confirmation must occur before `held_expires_at`, failing with `ERR_HOLD_EXPIRED` (HTTP 410). Seventeenth (priority 17), supersession: a deliverable can be retired only when a newer deliverable exists for the same project and revision round, failing with `ERR_NO_SUPERSEDING_DELIVERABLE` (HTTP 409). Eighteenth (priority 18), deliverable loudness and format compliance: the compliance evaluation must pass before a deliverable is marked `READY`, failing with `ERR_QC_FAILED` (HTTP 422). Nineteenth (priority 19), source specification: a source asset's `sample_rate_hz` and `bit_depth` must meet the platform target before it can be QC-passed, failing with `ERR_SOURCE_BELOW_SPEC` (HTTP 422). Twentieth and last (priority 20), optimistic concurrency: the `expected_*_version` field must match the parent's current `version` on the two OCC-guarded writes, failing with `ERR_STALE_VERSION` (HTTP 412). Because the stale-version check runs last, a version mismatch is reported only after every other applicable guard has passed.

### 2.6. Studio Time Discipline

The studio schedules in half-hour grains. `scheduled_start_at` on a project, and `slot_start_at` and `slot_end_at` on a session slot, must each fall on minute :00 or :30 of an hour; a timestamp off the grid is rejected with `ERR_INVALID_TIME_BOUNDARY` (HTTP 400). A slot's `slot_end_at` must be strictly after its `slot_start_at`. A booking's `scheduled_duration_minutes` must be a multiple of 30 and lie between 60 and 480 minutes inclusive — that is, sessions run from one hour to eight hours.

Slot overlap uses half-open interval semantics: a slot occupies the span from its start (inclusive) to its end (exclusive). A requested window conflicts with an existing `BOOKED` or `HELD` slot for the same engineer only when the requested start is strictly before the existing slot's end and the existing slot's start is strictly before the requested end; two slots that merely touch at a boundary — one ending at the exact minute the other begins — do not conflict. A conflict is rejected with `ERR_SLOT_CONFLICT` (HTTP 409).

Capacity is evaluated forward-looking over the requested window. The window runs from `scheduled_start_at` to `scheduled_start_at` plus `scheduled_duration_minutes`, end-exclusive. The engineer's booked minutes inside the window are the sum, over every session slot of that engineer in `BOOKED` or `HELD` status that intersects the window (a `HELD` slot whose `held_expires_at` has been reached counts as already released and contributes nothing), of the overlap length in minutes — measured from the later of the slot's `slot_start_at` and the window start to the earlier of the slot's `slot_end_at` and the window end. The window spans a number of days equal to its length in seconds divided by 86,400, rounded up to a whole day; the engineer's capacity inside the window is `capacity_minutes_per_day` multiplied by that day count, and the remaining capacity is the capacity minus the booked minutes. An engineer is eligible for the booking only when the remaining minutes are at least `scheduled_duration_minutes` and the engineer's `availability_status` is `AVAILABLE`; insufficient remaining capacity is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422). All capacity arithmetic is performed in integer minutes.

Soft holds expire. When a session slot is created it enters `HELD` and the server stamps `held_expires_at` as its creation time plus fifteen minutes. A hold is expired the moment the logical clock reaches or passes `held_expires_at`; the system performs this check on every read (GET) request — sweeping every slot and revision round in the system, not only the resource being read — and an expired hold is released automatically.

### 2.7. Money, Credits, and Pricing Precision

All monetary values are integer cents. Rush multipliers are expressed in basis points on a scale of 10,000: a `multiplier_bp` of 10000 is a 1.0x multiplier, 15000 is 1.5x, 20000 is 2.0x, and 30000 is 3.0x. Both the provisional quote and the final quote are computed with round-half-up rounding applied exactly once, at the final step of the chain — intermediate products are never rounded. Capacity is computed in integer minutes, loudness comparisons are carried at one decimal place, and recall-fee arithmetic yields integer cents.

Each client carries a prepaid ledger, `account_credit_cents`. The ledger is debited when a revision round is approved (by the project's `final_price_cents`) and when an archive recall is requested (by the bundle's `recall_fee_cents`). A studio manager may also post manual credit adjustments carrying a positive or negative `amount_cents` together with a `reason`. No debit may drive the balance below zero: if the balance after the debit would be negative, the operation is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402). Each client also carries `lifetime_revision_count`, an aggregate count of every revision round ever opened across all of the client's projects, which feeds the studio's VIP-tier evaluation.

### 2.8. Loudness and Delivery Targets

Every distribution target is captured as a PlatformProfile. The `platform_code` is one of `SPOTIFY`, `APPLE_MUSIC`, `YOUTUBE_MUSIC`, `TIDAL`, `DEEZER`, `BANDCAMP`, `VINYL`, `CD`, or `CLUB`, and is unique per profile row. The loudness target `integrated_lufs` must lie between -30.0 and -5.0 LUFS inclusive; the true-peak ceiling `true_peak_dbtp` must lie between -6.0 and 0.0 dBTP inclusive; the maximum loudness range `loudness_range_lu` must be greater than zero. The format requirements are `required_sample_rate_hz` (for example 44100, 48000, or 96000), which must be greater than zero, `required_bit_depth` (16, 24, or 32), and a `container_format` of `WAV`, `AIFF`, `FLAC`, `MP3_320`, `AAC_256`, `DDP`, or `VINYL_PREMASTER`. A profile creation that violates any of these bounds is rejected with `ERR_INVALID_REQUEST` (HTTP 400), and a duplicate `platform_code` is rejected with `ERR_INVALID_REQUEST` at HTTP 409.

A deliverable is judged compliant against the project's platform profile on four conditions, and all four must hold. The measured `integrated_lufs` must sit within 0.5 LU of the profile's `integrated_lufs` — that is, the absolute difference between measured and target loudness must be no more than half an LU, with loudness comparisons carried at one decimal place. The measured `true_peak_dbtp` must not exceed the profile's `true_peak_dbtp` ceiling. The measured `loudness_range_lu` must not exceed the profile's `loudness_range_lu`. And the encoded format must match exactly: the deliverable's `sample_rate_hz` must equal the profile's `required_sample_rate_hz` and its `bit_depth` must equal the profile's `required_bit_depth`.

### 2.9. Optimistic Concurrency Control

Two write operations are guarded by optimistic concurrency control, and only those two take a version field.

A booking request must carry `expected_client_version`, holding the client's `version` as the caller last observed it. If the client record's current `version` has advanced since that observation — for instance because another writer has just suspended the client, which legitimately releases held session slots and cancels early-stage projects, leaving the caller's view of the client's status stale — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412), and no booking side effects occur.

A revision-round submission must carry `expected_project_version`, holding the project's `version` as the engineer last observed it. If the project's current `version` has advanced since that observation — for instance because the client has just rejected a prior round, which bumps the project's version and opens a fresh round, leaving the engineer's view of the active round stale — the submission is rejected with `ERR_STALE_VERSION` (HTTP 412), and the round remains untouched.

Endpoints not listed here do not take a version field. On every OCC-guarded endpoint the stale-version check is the final guard evaluated, per §2.5.

### 2.10. Nested Resource Retrieval

For any request whose path contains multiple resource identifiers — an `id` segment for the parent followed by a nested segment such as a round identifier `rid`, or a deliverable under a project — the system validates existence strictly left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. A request naming a revision round under a project that does not exist fails on the project before the round is ever examined, and the same discipline applies to deliverables, source assets, QC reports, and metadata tags nested beneath their parents.

### 2.11. The Logical Clock

All time-dependent behavior in the system — hold expiries, revision deadlines, restore flows — reads a server-side logical clock, never the wall clock. Before any clock-setting call, the logical clock reads the default instant 2026-05-01T00:00:00Z, and it must never fall back to real wall-clock time. A studio-manager-only, test-driving capability advances the logical clock to a supplied instant carried in the `to_iso8601` field. Operations that compare "now" against a deadline or an expiry all read this same clock.

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Account Standing

A studio manager registers a new client by supplying the `legal_name` — the label or artist's legal entity name used on contracts and invoices — and a `contact_email`, which must be unique across the studio — a duplicate is rejected with `ERR_INVALID_REQUEST` at HTTP 409. A freshly registered client starts in `PROSPECT` status with `account_credit_cents` at zero and `lifetime_revision_count` at zero. The client roster can be listed with an optional `status` filter alongside `limit` and `offset`, and individual clients can be fetched by managers, QA, and the client themselves.

Activation moves a client from `PROSPECT` to `ACTIVE`, and a first activation is only possible once at least one project row exists for that client, in any status at all — an activation attempted before any project exists fails with `ERR_INVALID_STATE` (HTTP 409); the transition increments the client's `version` and refreshes `updated_at`. Reactivation from `SUSPENDED` back to `ACTIVE` carries no additional precondition and likewise increments `version`.

Suspension is the heavy hammer. Moving a client from `ACTIVE` to `SUSPENDED` releases every session slot in `HELD` status attached to projects owned by that client, cancels every project of that client still in `DRAFT`, `BOOKED`, or `INTAKE` — each landing in `CANCELLED` — and increments the client's `version`.

Termination is permanent and guarded. A client may move from `ACTIVE` to `TERMINATED`, or from `SUSPENDED` to `TERMINATED`, only when none of the client's projects is in flight — no project in `BOOKED`, `INTAKE`, `QC_PASSED`, `MASTERING`, `REVISION`, `APPROVED`, or `DELIVERING`; an attempt made while such a project exists fails with `ERR_INVALID_STATE` (HTTP 409). `TERMINATED` is terminal; any further transition attempted on an entity that has already reached a terminal state is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409). Both termination paths increment the client's `version`.

A studio manager may adjust a client's prepaid balance at any time by posting a signed `amount_cents` — positive to add credit, negative to remove it — together with a `reason`; the adjustment lands directly on `account_credit_cents`; a negative adjustment that would drive the balance below zero is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402), and a successful adjustment returns the updated Client record with `201 Created`.

### 3.2. Roster, Platform Targets, and Rush Pricing Setup

Before any project can be booked, the studio manager assembles three bodies of configuration.

The engineer roster comes first. Onboarding an engineer records a `display_name`, a skill `tier` of `JUNIOR`, `STAFF`, `SENIOR`, or `MASTER`, an `hourly_rate_cents` that must be greater than zero, and a `capacity_minutes_per_day` that must be at least zero — violations are rejected with `ERR_INVALID_REQUEST` (HTTP 400). New engineers start with `availability_status` set to `AVAILABLE` and an `active_project_count` of zero. Availability can later be moved among `AVAILABLE`, `ON_LEAVE`, and `INACTIVE` by a manager or by the engineer acting on their own record; an engineer attempting to change another engineer's record is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403). The `active_project_count` tracks how many of the engineer's assigned projects currently sit in `BOOKED`, `INTAKE`, `MASTERING`, or `REVISION`; it bumps when a booking assigns the engineer and again when a recalled project resumes into mastering, and it decrements when a project is archived, when a booked or in-progress project is cancelled, and when a booked slot is cancelled. The roster list supports `tier` and `availability_status` filters.

Platform profiles come second, following §2.8: one row per distribution target, its `platform_code` unique, with the loudness, true-peak, range, sample-rate, bit-depth, and container requirements that every deliverable will later be judged against. The profile list supports a `platform_code` filter.

Rush pricing comes third. A RushTierRule prices one turnaround `tier` — `STANDARD`, `EXPRESS`, `RUSH`, or `EMERGENCY`, unique per row, a duplicate `tier` rejected with `ERR_INVALID_REQUEST` at HTTP 409 — and carries five figures: `multiplier_bp`, the price multiplier in basis points on the 10,000 scale; `sla_hours`, the turnaround allowance per revision round, which must be greater than zero (a violation is rejected with `ERR_INVALID_REQUEST` (HTTP 400)); `surcharge_breach_cents`, a flat surcharge applied whenever a round's SLA is breached; `included_revision_rounds`, the number of revision rounds bundled into the base price; and `per_round_cents`, the price of each round beyond the included count. The rule list supports a `tier` filter. Wherever this specification refers to a project's rush-tier rule and no rule row exists for that tier, a default rule applies: `multiplier_bp` 10000, `sla_hours` 24, `surcharge_breach_cents` 0, `included_revision_rounds` 0, `per_round_cents` 0.

### 3.3. Booking a Mastering Session

A client opens work by creating a project for themselves — the payload's `client_id` must match the caller's own identity, otherwise the request fails with `ERR_CLIENT_NOT_OWNER` (HTTP 403). The creation payload carries the release `title`, an optional `upc`, the `target_platform_profile_id` of the distribution target the master must satisfy, the requested `scheduled_start_at`, the `scheduled_duration_minutes`, and an optional `rush_tier` that defaults to `STANDARD`. The `upc`, when present, is a 12-digit numeric string and must be unique across every project in the studio — a collision on creation, or on any later update of the project, is rejected with `ERR_DUPLICATE_UPC` (HTTP 409) — and a malformed `upc` fails format validation with `ERR_INVALID_FORMAT` (HTTP 400). The session must respect the studio time grid of §2.6: a start off the 30-minute boundary fails with `ERR_INVALID_TIME_BOUNDARY` (HTTP 400), and the duration must be a multiple of 30 between 60 and 480 minutes inclusive, failing with `ERR_INVALID_REQUEST` (HTTP 400) otherwise. A new project starts in `DRAFT` with `revision_round_count`, `quoted_price_cents`, and `final_price_cents` at zero. The project list can be filtered by `client_id`, `status`, `assigned_engineer_id`, `target_platform_profile_id`, `current_revision_round_id`, and `archive_bundle_id`.

Booking moves the project `DRAFT → BOOKED` and is the most heavily guarded transition in the system. The client must be `ACTIVE` — booking against a suspended or prospective client fails with `ERR_ENTITY_NOT_ACTIVE` (HTTP 422) — and the `target_platform_profile_id` must resolve to a real profile row. The booking request must also carry `expected_client_version` per §2.9; a mismatch against the client record's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412). The engineer selector then scans the roster in onboarding order, considering only engineers whose `availability_status` is `AVAILABLE`, and selects the first engineer whose requested window does not overlap any of their existing `BOOKED` or `HELD` slots and whose remaining capacity inside the window — computed exactly as §2.6 prescribes, remaining minutes at least equal to `scheduled_duration_minutes` — covers the session; when no engineer qualifies, the booking fails with `ERR_SLOT_CONFLICT` (HTTP 409) if at least one `AVAILABLE` engineer was disqualified by an overlap, and with `ERR_CAPACITY_EXCEEDED` (HTTP 422) otherwise.

A successful booking performs its side effects atomically: a session slot in `BOOKED` status is created covering the window from `scheduled_start_at` for `scheduled_duration_minutes` (its `held_expires_at` is null — no hold expiry applies to a booked slot); the project's `assigned_engineer_id` is set to the selected engineer; the engineer's `active_project_count` increments; the provisional pricing variant runs and writes `quoted_price_cents`; and both the project's `version` and the client's `version` increment.

The provisional quote prices only the session itself. The base session hours are `scheduled_duration_minutes` divided by 60; the base charge is those hours multiplied by the assigned engineer's `hourly_rate_cents`; the rush multiplier is the project's tier rule `multiplier_bp` divided by 10,000; and the provisional price is the base charge multiplied by the rush multiplier, rounded half-up to integer cents at the very end of the chain with no intermediate rounding. Revision rounds are not billed provisionally — the quote assumes the booking stays within the included rounds, so billable rounds are taken as zero at this stage.

Cancellation is available while a project is in `DRAFT`, `BOOKED`, or `INTAKE`, to the owning client or a studio manager, and lands the project in the terminal `CANCELLED` state. Cancelling releases every session slot of the project still in `HELD` or `BOOKED` — each such slot moves to `RELEASED` — and decrements the engineer's `active_project_count`; for a `DRAFT` project the decrement applies only if an engineer was already assigned, while cancellation from `BOOKED` or `INTAKE` always carries an assigned engineer and always decrements. The project's `version` increments on each path.

### 3.4. Holding and Confirming Studio Time

Session slots have their own lifecycle, independent of any single project transition. A client or a studio manager can place a soft hold by creating a slot with an `engineer_id`, an optional `project_id` fixed at creation — null for a hold not placed on behalf of any project, and never reassigned afterwards — a `slot_start_at`, and a `slot_end_at`. A client may supply a `project_id` only for a project they own, and on reads a client sees only slots with no project attached or slots attached to their own projects. Both endpoints of the slot must sit on the 30-minute grid with the end strictly after the start (an end not strictly after the start is rejected with `ERR_INVALID_REQUEST` (HTTP 400)), and the overlap guard of §2.6 applies at creation: any clash with an existing `BOOKED` or `HELD` slot of the same engineer is rejected with `ERR_SLOT_CONFLICT` (HTTP 409). The slot is born in `HELD`, and the server stamps `held_expires_at` at creation time plus fifteen minutes.

Confirmation moves a hold `HELD → BOOKED` and is the client's action. It must happen before `held_expires_at`; a confirmation attempted at or after the expiry instant is rejected with `ERR_HOLD_EXPIRED` (HTTP 410). The engineer occupying the slot must also be `AVAILABLE` at confirmation time, failing with `ERR_ENTITY_NOT_ACTIVE` (HTTP 422) otherwise. The slot's `version` increments.

Holds that are not confirmed in time do not linger. A hold moves `HELD → RELEASED` either when the expiry instant is reached — the system checks on any read of a `HELD` slot as well as periodically — or when a client or studio manager releases it explicitly; either path frees the engineer's capacity window and increments the slot's `version`. When the project attached to a booked slot begins intake, the slot moves `BOOKED → CONSUMED` as a system event, recording that the reserved time was used. A studio manager may also cancel a `BOOKED` slot outright, moving it to `CANCELLED`; that cancellation cascades, pulling the attached project into `CANCELLED` when the project is still in `DRAFT`, `BOOKED`, or `INTAKE`, and decrementing the engineer's `active_project_count`. Slot listings can be filtered by `engineer_id`, `project_id`, and `status`.

### 3.5. Source Intake and Technical QC

Once a project is `BOOKED`, intake begins. The project moves `BOOKED → INTAKE` when the first source asset is uploaded to it or when the assigned engineer explicitly begins intake; either path requires the engineer to be `AVAILABLE`, failing with `ERR_ENTITY_NOT_ACTIVE` (HTTP 422) otherwise, and the transition consumes the project's booked slot per §3.4 while incrementing the project's `version`.

Uploading a source asset — open to the client and the engineer — records the original `filename`, a `sha256` checksum of the file content as 64 lowercase hexadecimal characters, the source's `sample_rate_hz` and `bit_depth`, a `duration_seconds` that must be greater than zero, and a `channels` count where 1 means mono, 2 means stereo, 6 means 5.1 surround, and 8 means 7.1 surround. An upload whose `sha256` is not 64 lowercase hexadecimal characters, whose `duration_seconds` is not greater than zero, or whose `channels` is not one of 1, 2, 6, or 8 is rejected with `ERR_INVALID_REQUEST` (HTTP 400). Uploads are accepted only while the project is `BOOKED` or `INTAKE`; any other project state fails the §2.5 state guard. On the upload path the engineer-availability check fires after the checksum-uniqueness guard. The checksum must be unique within the project: uploading content whose `sha256` is already present on the same project is rejected with `ERR_DUPLICATE_ASSET` (HTTP 409). Every asset lands with `qc_status` set to `PENDING`, and a project's asset list can be filtered by `qc_status`.

Technical QC then adjudicates each asset. Marking an asset passed moves it `PENDING → PASSED` and requires the source to meet the project's platform target: the asset's `sample_rate_hz` must be at least the profile's `required_sample_rate_hz` and its `bit_depth` must be at least the profile's `required_bit_depth`; a source below either bar is rejected with `ERR_SOURCE_BELOW_SPEC` (HTTP 422). Marking an asset failed moves it `PENDING → FAILED` and records the supplied `qc_failure_reason`, which is required. A studio manager retains an override: a failed asset can be waived, moving `FAILED → WAIVED`. Each of these transitions increments the asset's `version`.

When every source asset on the project has reached `PASSED` or `WAIVED` — a condition that holds vacuously when the project has no assets — the engineer can mark intake QC complete, moving the project `INTAKE → QC_PASSED` and incrementing its `version`; if any asset has not reached one of those states the call fails with `ERR_INVALID_STATE` (HTTP 409).

### 3.6. Mastering, Revision Rounds, and Client Approval

Starting mastering moves the project `QC_PASSED → MASTERING` and opens the first revision round: a RevisionRound with `round_index` 1 in `OPEN` status, stamped with `opened_at`. The project's `current_revision_round_id` points at the new round, its `revision_round_count` becomes 1, the client's `lifetime_revision_count` increments, and the project's `version` increments. Every round carries a `deadline_at`, computed as its `opened_at` plus the `sla_hours` of the project's rush-tier rule — an `EXPRESS` project and an `EMERGENCY` project live under different clocks for the same work. Round indexes are one-based, monotonically increasing per project, and never reused; a round's list supports a `status` filter, and each round also carries free-text `notes` for client feedback or engineer commentary.

Submitting a revised master is the engineer's action on the round they own — an engineer acting on a project assigned to someone else is rejected with `ERR_ENGINEER_NOT_ASSIGNED` (HTTP 403). Submission requires the project to be in `MASTERING` with the round still `OPEN`; a project with no open current round for the requested operation fails with `ERR_NO_ACTIVE_ROUND` (HTTP 409). The request must carry `expected_project_version` per §2.9, and a mismatch with the project's current `version` is rejected with `ERR_STALE_VERSION` (HTTP 412) — this is the serialization point that prevents an engineer from submitting against a round the client has already moved past. The submission must also arrive no later than the round's `deadline_at`; a late submission is rejected with `ERR_SLA_BREACH` (HTTP 422). A successful submission moves the round `OPEN → SUBMITTED`, stamps `submitted_at`, moves the project `MASTERING → REVISION`, and increments both the round's and the project's `version`; an optional `notes` payload rides along. The response carries the updated round.

If a round is still `OPEN` when the logical clock passes its `deadline_at`, a system event — applied at the same read-time sweep as hold expiry — moves it `OPEN → EXPIRED`: the breach surcharge for the project's rush tier — the rule's `surcharge_breach_cents`, once per expired round — is folded into the final quote, the project's `final_price_cents` is recomputed and written at that moment (incrementing the project's `version` per §2.4), and the round's `version` increments.

The client then adjudicates each submitted round. Rejection moves the round `SUBMITTED → REJECTED`, stamps `resolved_at`, and immediately opens the next round with `round_index` one higher in `OPEN` status; the project's `current_revision_round_id` retargets, its `revision_round_count` increments, the client's `lifetime_revision_count` increments, and the project's `version` increments as the project returns `REVISION → MASTERING`. Approval moves the round `SUBMITTED → APPROVED`, stamps `resolved_at`, runs the final quote and writes `final_price_cents` in place of the provisional figure, debits the client's `account_credit_cents` by that amount — a debit that would push the balance negative is rejected with `ERR_INSUFFICIENT_CREDIT` (HTTP 402) — and moves the project `REVISION → APPROVED` with its `version` incremented. Both adjudication calls return the updated round.

The final quote recomputes from scratch at approval time. The base session hours remain `scheduled_duration_minutes` divided by 60, but the base charge now uses the engineer's current `hourly_rate_cents` at approval, not the rate observed at booking. The rush multiplier applies as before — the tier rule's `multiplier_bp` divided by 10,000 — producing the rush-adjusted base. Revision billing is then reconciled: the billable round count is the project's total `revision_round_count`, counting rounds in every status whether still open or already terminal, minus the tier rule's `included_revision_rounds`, floored at zero; each billable round costs the rule's `per_round_cents`. SLA breaches add their own line: the number of the project's rounds in `EXPIRED` status multiplied by the rule's `surcharge_breach_cents`. The final price is the rush-adjusted base plus the extra-round charges plus the breach surcharges, rounded half-up to integer cents at the final step.

### 3.7. Deliverable Builds, Quality Control, and Metadata

With a round in flight, the engineer builds deliverables against it. Creating a deliverable names the producing `revision_round_id`, a `deliverable_kind` of `DDP`, `STEM_PACK`, `INSTRUMENTAL`, `MASTER_WAV`, `MASTER_FLAC`, `MASTER_AAC`, or `VINYL_PREMASTER`, and the measured characteristics of the build: `integrated_lufs`, `true_peak_dbtp`, `loudness_range_lu`, `sample_rate_hz`, and `bit_depth`. Creation requires only that the named `revision_round_id` exists and belongs to the project — neither the project's nor the round's status is consulted, and an unknown or cross-project round fails with `ERR_NOT_FOUND` (HTTP 404). The deliverable records its parent `project_id`, starts in `BUILDING`, and the build lists — both per-project and studio-wide — can be filtered by `project_id`, `revision_round_id`, `deliverable_kind`, `status`, and the `qc_report_id` of the latest QC run.

When a build is ready for judgment, the engineer submits it for QC, moving `BUILDING → QC_PENDING`. QC evidence accumulates as QCReport rows: each report records the `deliverable_id` it judges together with a denormalized `project_id` for query speed, a `check_code` of `LOUDNESS_IN_TOL`, `TRUE_PEAK_IN_TOL`, `LRA_IN_TOL`, `FORMAT_MATCH`, `ISRC_PRESENT`, `UPC_MATCH`, `CLIP_FREE`, `DC_OFFSET_OK`, or `PHASE_COHERENT`, a boolean `passed`, and, when applicable, a numeric `measured_value` with the `tolerance` that was applied. QA checkers author these reports, with engineers also permitted to record results (no engineer-assignment match is required); the report listings can be filtered by `project_id`, `deliverable_id`, `check_code`, and `passed` — the `passed` filter accepting the strings `true` and `false` case-insensitively. Recording a report also points the deliverable's `qc_report_id` at the new report — a mutation that increments the deliverable's `version` per §2.4 — and reports may be recorded against a deliverable in any status.

The verdict belongs to QA alone. Passing a deliverable moves it `QC_PENDING → READY` and requires two things together: every QCReport row on the deliverable must have `passed` true, and the loudness-and-format compliance evaluation of §2.8 must pass — measured loudness within half an LU of target, true peak and loudness range at or under their ceilings, and an exact sample-rate and bit-depth match. A failure on either front is rejected with `ERR_QC_FAILED` (HTTP 422). Failing a deliverable moves it `QC_PENDING → QC_FAILED` when at least one report has `passed` false — an attempt to fail a deliverable with no failing report is rejected with `ERR_QC_FAILED` (HTTP 422) — and an engineer can then rebuild it, moving `QC_FAILED → BUILDING` for another attempt.

Metadata embedding comes next, by the engineer, and only on a `READY` deliverable. The payload carries an `isrc` — a 12-character code of two uppercase letters, three uppercase letters or digits, and seven digits, such as USRC17607839, unique per deliverable kind within the project (a collision with a live, non-`REVOKED` tag is rejected with `ERR_INVALID_REQUEST` at HTTP 409) — and an optional `upc` in the 12-digit form. Malformed codes are rejected with `ERR_INVALID_FORMAT` (HTTP 400), and when the parent project carries a `upc`, the tag's `upc` must equal it exactly, failing with `ERR_METADATA_MISMATCH` (HTTP 422) otherwise. Embedding creates the MetadataTag already in `EMBEDDED` status with `embedded_at` stamped (its `DRAFT` state is never persisted), advances the deliverable `READY → EMBEDDED`, and increments both records' `version`.

Verification closes the loop. QA verifies an embedded deliverable — moving it `EMBEDDED → VERIFIED` — only while its most recently created tag's `embedding_status` is `EMBEDDED`; if no such tag exists the call fails with `ERR_INVALID_STATE` (HTTP 409). Verification flips the tag to `VERIFIED`, stamps `verified_at`, and increments both records' `version`. A tag can also be verified independently on its own, moving `EMBEDDED → VERIFIED` with the same stamping. When QA detects that an embedded ISRC or UPC differs from the authoritative source, they flag the tag `EMBEDDED → MISMATCH`, and a studio manager can then revoke it, moving `MISMATCH → REVOKED`.

Retirement keeps the catalog clean. A studio manager may retire a `VERIFIED` deliverable only when a newer deliverable exists for the same project and revision round, newer meaning created later, in any status; without a superseding build the request is rejected with `ERR_NO_SUPERSEDING_DELIVERABLE` (HTTP 409). Retiring moves the deliverable to the terminal `RETIRED` state and revokes any linked metadata tags, setting their `embedding_status` to `REVOKED`.

### 3.8. Delivery, Archival, and Recall

Delivery begins once the client has approved a round: the engineer moves the project `APPROVED → DELIVERING`, which requires at least one deliverable produced for the project's current revision round to have reached `VERIFIED`, failing with `ERR_INVALID_STATE` (HTTP 409) otherwise. Finalizing delivery moves `DELIVERING → DELIVERED` and is stricter — every deliverable for the current round must be in `VERIFIED` or `RETIRED` before the project can be called delivered, failing with `ERR_INVALID_STATE` (HTTP 409) otherwise. Each step increments the project's `version`.

Archival is a studio-manager action on a `DELIVERED` project, carrying the chosen `storage_class` — `HOT`, `WARM`, `COLD`, or `GLACIER` — and the `archive_size_bytes` actually persisted, which must be at least zero (a negative size is rejected with `ERR_INVALID_REQUEST` (HTTP 400)). Archiving creates the project's ArchiveBundle with `recall_status` set to `NONE` — exactly one archive bundle may exist per project — writes the project's `archive_bundle_id`, moves the project `DELIVERED → ARCHIVED`, decrements the assigned engineer's `active_project_count`, and increments the project's `version`. The response carries the created ArchiveBundle. The archive list supports `project_id` and `recall_status` filters.

Recall reopens the archive at a price. The owning client recalls an `ARCHIVED` project — either from the project itself or directly against its archive bundle; both entry points perform the same operation — which requires the bundle's `recall_status` to be `NONE` — a bundle in `PENDING` or `RESTORING` fails with `ERR_INVALID_STATE` (HTTP 409), one in `RESTORED` or `FAILED` with `ERR_ALREADY_TERMINAL` (HTTP 409), and the project-path entry on a project with no archive bundle fails with `ERR_NOT_FOUND` (HTTP 404). The response carries the updated bundle. The recall moves the bundle `NONE → PENDING`, stamps `recalled_at`, computes the recall fee into `recall_fee_cents`, debits the client's `account_credit_cents` by that fee with the usual `ERR_INSUFFICIENT_CREDIT` (HTTP 402) guard, moves the project `ARCHIVED → RECALLED`, and increments the project's `version`. The fee is tiered by storage class over the archive's size in whole gigabytes: the byte count is divided by 1,073,741,824 and rounded up — an archive even one byte over a gigabyte boundary bills the next whole gigabyte, and any positive size under a gigabyte still bills one, while a zero-byte archive bills zero gigabytes — then multiplied by the class rate: 500 cents per gigabyte for `HOT`, 1,000 for `WARM`, 2,000 for `COLD`, and 4,000 for `GLACIER`. A floor protects the studio from trivial recalls: if the computed fee is under 1,000 cents, the charge is 1,000 cents — ten dollars — regardless.

Restoration is manager-driven. Beginning the restore moves the bundle `PENDING → RESTORING`; completing it moves `RESTORING → RESTORED` and stamps `restored_at`; a restore that cannot be completed is marked `RESTORING → FAILED`. Once the bundle reads `RESTORED`, the engineer resumes the project, moving it `RECALLED → MASTERING` — attempting the resume while the bundle reads `FAILED` is rejected with `ERR_ALREADY_TERMINAL` (HTTP 409), and while it reads anything else short of `RESTORED` with `ERR_INVALID_STATE` (HTTP 409) — which increments the engineer's `active_project_count` and the project's `version` and returns the project to the mastering loop of §3.6.

## 4. Endpoint Definitions

Operations that create new, stand-alone resources (a client, an engineer, a platform profile, a rush-tier rule, a project, a session slot, a source asset, a deliverable, a metadata tag, a QC report, or a credit adjustment) return a `201 Created` status code. Operations that modify an existing resource or drive a state transition return a `200 OK` status code.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/studio/_clock/set_current_utc` | Set the logical clock to the given ISO-8601 UTC instant | StudioManager |
| POST | `/studio/clients` | Register a new client | StudioManager |
| GET | `/studio/clients` | List clients; supports status filter, pagination | StudioManager, QAChecker, Engineer |
| GET | `/studio/clients/{id}` | Get single client | StudioManager, Client, QAChecker |
| POST | `/studio/clients/{id}/activate` | Activate a PROSPECT or SUSPENDED client | StudioManager |
| POST | `/studio/clients/{id}/suspend` | Suspend an ACTIVE client (cascades to projects/slots) | StudioManager |
| POST | `/studio/clients/{id}/terminate` | Terminate a client (only when no in-flight projects) | StudioManager |
| POST | `/studio/clients/{id}/credit-adjustments` | Add or remove credit from a client's account | StudioManager |
| POST | `/studio/engineers` | Onboard a new engineer | StudioManager |
| GET | `/studio/engineers` | List engineers; supports tier, availability_status filters | StudioManager, Client, QAChecker |
| GET | `/studio/engineers/{id}` | Get single engineer | StudioManager, Engineer, QAChecker |
| POST | `/studio/engineers/{id}/set-availability` | Set engineer availability (AVAILABLE, ON_LEAVE, INACTIVE) | StudioManager, Engineer |
| POST | `/studio/platform-profiles` | Define a distribution platform target | StudioManager |
| GET | `/studio/platform-profiles` | List platform profiles | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/platform-profiles/{id}` | Get single platform profile | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/rush-tier-rules` | Define pricing/SLA rule for a rush tier | StudioManager |
| GET | `/studio/rush-tier-rules` | List rush tier rules | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/projects` | Create a new mastering project (DRAFT) | Client |
| GET | `/studio/projects` | List projects; supports client_id, status, assigned_engineer_id, target_platform_profile_id, current_revision_round_id, archive_bundle_id filters | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/projects/{id}` | Get single project | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/projects/{id}/book` | Confirm booking, assign engineer, run provisional quote (OCC-guarded on Client) | Client |
| POST | `/studio/projects/{id}/cancel` | Cancel a DRAFT/BOOKED/INTAKE project | Client, StudioManager |
| POST | `/studio/projects/{id}/begin-intake` | Engineer begins intake on a BOOKED project | Engineer |
| POST | `/studio/projects/{id}/qc/complete` | Mark intake QC complete; requires all source assets passed/waived | Engineer |
| POST | `/studio/projects/{id}/start-mastering` | Begin mastering; opens first revision round | Engineer |
| POST | `/studio/projects/{id}/deliver` | Begin delivery phase | Engineer |
| POST | `/studio/projects/{id}/finalize-delivery` | Mark delivery complete | Engineer |
| POST | `/studio/projects/{id}/archive` | Archive a DELIVERED project | StudioManager |
| POST | `/studio/projects/{id}/recall` | Recall an archived project | Client |
| POST | `/studio/projects/{id}/resume-from-recall` | Resume a recalled project to MASTERING | Engineer |
| POST | `/studio/session-slots` | Create a HELD slot (30-min boundary required) | Client, StudioManager |
| GET | `/studio/session-slots` | List session slots; supports engineer_id, project_id, status filters | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/session-slots/{id}` | Get single slot | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/session-slots/{id}/confirm` | Confirm a HELD slot → BOOKED | Client |
| POST | `/studio/session-slots/{id}/release` | Release a HELD slot | Client, StudioManager |
| POST | `/studio/session-slots/{id}/cancel` | Cancel a BOOKED slot (cascades to project) | StudioManager |
| POST | `/studio/projects/{id}/source-assets` | Upload a source audio asset to a project | Client, Engineer |
| GET | `/studio/projects/{id}/source-assets` | List source assets for a project | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/source-assets/{id}` | Get single source asset | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/source-assets/{id}/qc-pass` | Mark source asset QC pass | Engineer, QAChecker |
| POST | `/studio/source-assets/{id}/qc-fail` | Mark source asset QC fail | Engineer, QAChecker |
| POST | `/studio/source-assets/{id}/qc-waive` | Studio manager waives a failed QC | StudioManager |
| GET | `/studio/projects/{id}/rounds` | List revision rounds for a project | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/rounds/{id}` | Get single revision round | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/projects/{id}/rounds/{rid}/submit` | Engineer submits revised master (OCC-guarded on Project) | Engineer |
| POST | `/studio/projects/{id}/rounds/{rid}/approve` | Client approves round; triggers final quote + debit | Client |
| POST | `/studio/projects/{id}/rounds/{rid}/reject` | Client rejects round; opens next round | Client |
| POST | `/studio/projects/{id}/deliverables` | Create a deliverable build | Engineer |
| GET | `/studio/projects/{id}/deliverables` | List deliverables for a project; supports revision_round_id, qc_report_id filters | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/deliverables` | List deliverables; supports project_id, revision_round_id, qc_report_id, deliverable_kind, status filters | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/deliverables/{id}` | Get single deliverable | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/deliverables/{id}/submit-qc` | Submit deliverable for QC | Engineer |
| POST | `/studio/deliverables/{id}/qc-pass` | QA marks deliverable QC passed (requires all QCReports pass) | QAChecker |
| POST | `/studio/deliverables/{id}/qc-fail` | QA marks deliverable QC failed | QAChecker |
| POST | `/studio/deliverables/{id}/rebuild` | Rebuild a QC_FAILED deliverable | Engineer |
| POST | `/studio/deliverables/{id}/metadata-tags` | Embed ISRC/UPC metadata into deliverable | Engineer |
| POST | `/studio/deliverables/{id}/verify-metadata` | QA verifies embedded metadata | QAChecker |
| POST | `/studio/deliverables/{id}/retire` | Retire a superseded deliverable | StudioManager |
| GET | `/studio/deliverables/{id}/metadata-tags` | List metadata tags for a deliverable | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/metadata-tags/{id}` | Get single metadata tag | StudioManager, Client, Engineer, QAChecker |
| POST | `/studio/metadata-tags/{id}/verify` | Verify a metadata tag independently | QAChecker |
| POST | `/studio/metadata-tags/{id}/flag-mismatch` | Flag a metadata mismatch | QAChecker |
| POST | `/studio/metadata-tags/{id}/revoke` | Revoke a mismatched tag | StudioManager |
| POST | `/studio/deliverables/{id}/qc-reports` | Record a QC check result for a deliverable | QAChecker, Engineer |
| GET | `/studio/projects/{id}/qc-reports` | List QC reports for a project (across its deliverables) | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/qc-reports` | List QC reports across deliverables; supports project_id, deliverable_id, check_code, passed filters | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/deliverables/{id}/qc-reports` | List QC reports for a deliverable; supports project_id filter | StudioManager, Client, Engineer, QAChecker |
| GET | `/studio/archive-bundles` | List archive bundles; supports project_id, recall_status filters | StudioManager, Client, QAChecker |
| GET | `/studio/archive-bundles/{id}` | Get single archive bundle | StudioManager, Client, QAChecker |
| POST | `/studio/archive-bundles/{id}/recall` | Client initiates a recall (alternate entry point) | Client |
| POST | `/studio/archive-bundles/{id}/begin-restore` | Begin restore | StudioManager |
| POST | `/studio/archive-bundles/{id}/complete-restore` | Mark restore complete | StudioManager |
| POST | `/studio/archive-bundles/{id}/fail-restore` | Mark restore failed | StudioManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_UNAUTHORIZED` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_FORMAT` | 400 Bad Request |
| `ERR_INVALID_TIME_BOUNDARY` | 400 Bad Request |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_ALREADY_TERMINAL` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_ENTITY_NOT_ACTIVE` | 422 Unprocessable Entity |
| `ERR_SLOT_CONFLICT` | 409 Conflict |
| `ERR_CAPACITY_EXCEEDED` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_ASSET` | 409 Conflict |
| `ERR_DUPLICATE_UPC` | 409 Conflict |
| `ERR_METADATA_MISMATCH` | 422 Unprocessable Entity |
| `ERR_INSUFFICIENT_CREDIT` | 402 Payment Required |
| `ERR_SLA_BREACH` | 422 Unprocessable Entity |
| `ERR_HOLD_EXPIRED` | 410 Gone |
| `ERR_NO_SUPERSEDING_DELIVERABLE` | 409 Conflict |
| `ERR_QC_FAILED` | 422 Unprocessable Entity |
| `ERR_SOURCE_BELOW_SPEC` | 422 Unprocessable Entity |
| `ERR_NO_ACTIVE_ROUND` | 409 Conflict |
| `ERR_ENGINEER_NOT_ASSIGNED` | 403 Forbidden |
| `ERR_CLIENT_NOT_OWNER` | 403 Forbidden |
