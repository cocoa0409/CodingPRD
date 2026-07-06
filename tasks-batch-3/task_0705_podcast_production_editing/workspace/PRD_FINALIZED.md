# Podcast Production & Editing API — Product Requirements Document

## 1. Introduction

This document specifies the requirements for the Podcast Production & Editing Service, a back-office platform that coordinates the full arc of producing a podcast episode: onboarding a show and fixing its format, booking recording sessions and capturing audio in the studio or remotely, editing and mastering toward a loudness target, assembling show notes and transcripts, scheduling and publishing, and finally settling money. The platform serves four distinct constituencies — the production engineers who run capture and editing, the show owners who commission and review the work, the sponsorship operators who place advertising into episodes, and the platform operators who administer contracts, billing, and the engineer roster.

The business problem the API solves is that podcast production is simultaneously a *creative pipeline* and a *commercial relationship*, and the two are entangled. An episode cannot progress through editing if the show's commercial standing has lapsed; an invoice's surcharge depends on how much the show has already paid this lifetime; a retainer client's monthly allotment must be consumed in the order episodes actually went live. The service therefore treats every show as carrying a derived **production posture** that gates creative work based on the health of its contracts and invoices, and it treats billing as supporting two parallel commercial models — per-episode and retainer — whose arithmetic differs but whose ledger must stay consistent. The requirements below describe a single source of truth for that entangled state.

A note on time: the service runs on a **logical clock** rather than wall-clock time, so that turnaround deadlines, session windows, and billing periods are fully deterministic and testable. All timestamps the system records are read from this logical clock.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and cross-cutting principles that apply across every endpoint.

### 2.1. User and Role-Based Access Control

Every request to the API must carry two HTTP headers identifying the caller: `X-User-ID`, which names the acting principal, and `X-User-Role`, which declares the capacity in which they act. A request that omits either header, or that supplies an `X-User-Role` value that is not one of the recognized roles, is rejected with `ERR_UNAUTHENTICATED`. A request whose role is recognized but is not permitted to perform the requested operation (per the authorization column of the endpoint table in §4) is rejected with `ERR_FORBIDDEN_ROLE`.

The system recognizes exactly four roles: `PlatformAdmin`, `ShowOwner`, `ProducerEng`, and `AdOps`.

The four roles differ in how `X-User-ID` relates to persisted data:

- When `X-User-Role` is `ShowOwner`, `X-User-ID` is the `id` of the acting `Show`; ownership checks on any resource that ultimately references a `Show` compare the resource's show linkage to `X-User-ID`. A `ShowOwner` acting on an episode, a deliverable, an invoice, or a retainer cycle that does not chain back to their own show is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `ProducerEng`, `X-User-ID` is the `id` of the acting `Engineer`; ownership checks on a session compare the session's engineer linkage to `X-User-ID`, so an engineer operating another engineer's session is rejected with `ERR_NOT_RESOURCE_OWNER`.
- When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.
- When `X-User-Role` is `AdOps`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity. The server may record it but does not compare it to any entity's `id`.

`PlatformAdmin` is the operator role: it owns contract lifecycle, retainer cycles, the engineer roster, invoice administration (marking overdue, voiding), episode archival, and the logical clock. `ShowOwner` is the client: it commissions episodes, reviews and approves or sends back edits, cancels episodes, and pays or disputes its own invoices. `ProducerEng` is the production engineer: it books and runs sessions, locks assets, submits and schedules edits, publishes, and manages deliverables and asset versions. `AdOps` is the sponsorship coordinator: it manages ad campaigns, slot placement, and revenue reconciliation. Creating a show is shared between `PlatformAdmin` and `ShowOwner`; creating an episode is shared between `ShowOwner` and `PlatformAdmin`; accepting an asset version is shared between `ShowOwner` and `ProducerEng`.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return. If not provided, it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0, with a minimum of 0. A `limit` outside the inclusive range of 1 to 100, or an `offset` below 0, is rejected with `ERR_INVALID_PAGINATION`.

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp in ascending order.

Paginated list responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Versioning

All primary resources carry a system-managed set of fields. The `id` is a server-minted UUID with no type prefix, represented as a canonical hyphenated RFC 4122 string (for example `e34d66ea-7b68-4e89-b579-e2efd8078a48`) rather than a dashless hex form. The `created_at` field is an ISO 8601 UTC timestamp with three fractional digits, fixed at creation. The `updated_at` field is an ISO 8601 UTC timestamp with three fractional digits, refreshed on every mutation to the resource. The `version` field is an integer that begins at its initial value and increments by one on every mutation, and it is the basis for optimistic concurrency control (§2.11).

Every timestamp value the system emits in a response is formatted uniformly as an ISO 8601 UTC timestamp with exactly three fractional digits (milliseconds) and a trailing `Z`. This applies not only to the common `created_at` and `updated_at` fields but equally to every domain timestamp field — for example `activated_at`, `recording_ended_at`, `assets_complete_at`, `turnaround_due_utc`, `published_at`, `completed_at`, `closed_at`, and the session and retainer-cycle window fields (`scheduled_start_utc`, `scheduled_end_utc`, `cycle_start_utc`, `cycle_end_utc`) — which are normalized to this same three-fractional-digit form on output regardless of the precision in which they were supplied or stamped.

Every entity in this system — `Show`, `EngagementContract`, `RetainerCycle`, `Episode`, `Session`, `Engineer`, `Deliverable`, `AssetVersion`, `Invoice`, `AdCampaign`, and `AdSlot` — carries the full set: `id`, `created_at`, `updated_at`, and `version`. None of these resources is treated as immutable-after-creation, so none omits `updated_at` or `version`.

When the server derives or recomputes a field on a resource as a side effect of some operation — for example recomputing a show's posture or a deliverable's current version pointer — that recomputation is itself a mutation: it refreshes `updated_at` and increments `version` on the resource whose derived field changed.

### 2.5. Production Posture: The Commercial Gate

Each `Show` carries a computed `production_posture` field with one of three values — `ACTIVE`, `ON_HOLD`, or `SUSPENDED` — that gates the creative pipeline based on the show's commercial health. A newly created show starts `SUSPENDED`, because no contract has yet been activated for it. The posture is never set directly by a client; it is recomputed after every contract, invoice, or episode mutation that affects the show, by evaluating the following four conditions **in this fixed order and taking the first that matches**: first, if any invoice belonging to this show is in `DISPUTED` status, the posture is `SUSPENDED`; otherwise, if no engagement contract belonging to this show is in `ACTIVE` status, the posture is `SUSPENDED`; otherwise, if any invoice belonging to this show is in `OVERDUE` status, the posture is `ON_HOLD`; otherwise, the posture is `ACTIVE`.

The posture gates three operations. Creating an episode requires the owning show to be `ACTIVE`; a create against a non-`ACTIVE` show is rejected with `ERR_SHOW_NOT_ACTIVE`. Booking a session requires the owning show to be `ACTIVE`; a booking against a non-`ACTIVE` show is likewise rejected with `ERR_SHOW_NOT_ACTIVE`. Publishing an episode requires the owning show to be either `ACTIVE` or `ON_HOLD` — `ON_HOLD` deliberately lets in-flight work finish even though it blocks new intake — and a publish attempt while the show is `SUSPENDED` is rejected with `ERR_SHOW_SUSPENDED`.

The show also tracks `open_episode_count`, the number of its episodes whose status is none of `PUBLISHED`, `ARCHIVED`, or `CANCELLED`. This count is recomputed whenever an episode is created, cancelled, published, or archived. The show further tracks `lifetime_billed_cents`, a running sum described in §2.9.

### 2.6. The Editing Pipeline and Asset Consistency

The platform models the creative pipeline as a cyclic, branching state machine on the `Episode`, with a revision loop, and it propagates state upward from sessions and deliverables. Several operations on one resource mutate a second resource; each such cascade is described in §3, but the governing principle is that every cascade also refreshes `updated_at` and increments `version` on every resource it touches, and recomputes any of the show's derived fields that the cascade can affect.

Two consistency points deserve emphasis here. First, a deliverable's `current_version_no` is the highest `version_no` among accepted asset versions for that deliverable, and a deliverable becomes `READY` only once at least one of its versions has been accepted; both of these are maintained by the accept operation, not supplied by a client. Second, an episode's `raw_track_count` is frozen at asset-lock time and thereafter drives both the final turnaround deadline and the per-episode invoice's extra-track charge — it is not the same number as the `planned_track_count` captured at intake, and the two may legitimately differ.

### 2.7. Nested and Filtered Resource Retrieval

Resources in this system are organized as flat top-level collections linked by foreign-key fields rather than as deeply nested URL hierarchies. Reverse reachability is provided by filtered list endpoints: episodes can be filtered by `show_id` or `contract_id`; sessions by `episode_id` or `engineer_id`; deliverables by `episode_id`; asset versions by `deliverable_id` or by `supersedes_version_id`; invoices by `show_id`, `episode_id`, or `retainer_cycle_id`; ad campaigns by `show_id`; ad slots by `campaign_id` or `episode_id`; contracts by `show_id`; and retainer cycles by `contract_id`. Many list endpoints also accept a `status` filter, and the shows list accepts a `production_posture` filter and the engineers list an `active` filter.

For any operation, all resources referenced by the path and body are validated left-to-right; the first identifier that does not resolve to an existing resource causes the request to be rejected with `ERR_NOT_FOUND` before any business rule is evaluated.

### 2.8. Request Validation and Rule Ordering

Validation is layered, and the layers are evaluated in a fixed precedence so that the same request always fails for the same reason. The order is: authentication (`ERR_UNAUTHENTICATED`) first; then role authorization (`ERR_FORBIDDEN_ROLE`); then resource ownership for entity-backed roles (`ERR_NOT_RESOURCE_OWNER`); then existence of all referenced resources (`ERR_NOT_FOUND`); then request well-formedness — body parses, required fields present, types valid (`ERR_INVALID_REQUEST`); then enum membership, where any enum-typed field whose value is not a declared member is rejected with `ERR_INVALID_ENUM`; then, for list endpoints, pagination bounds (`ERR_INVALID_PAGINATION`). Only after all of those pass does the system evaluate state and business rules.

Among the state-and-business layer, transition legality is checked before concurrency and before the domain-specific business gates. Concretely, a transition endpoint first confirms the target resource is in a state from which the requested transition is legal — otherwise `ERR_INVALID_STATE` — and only then evaluates optimistic-concurrency staleness, posture gates, referential business rules, safety checks, temporal checks, and the remaining business constraints described throughout §3. Where a single endpoint carries several business checks, the specific ordering is called out in the workflow narrative that governs it.

Two enum fields are validated as windows rather than as memberships: a session's scheduled window must have its `scheduled_end_utc` strictly after its `scheduled_start_utc`, and a retainer cycle's window must have its `cycle_end_utc` strictly after its `cycle_start_utc`; either violation is rejected with `ERR_INVALID_WINDOW`. All datetime windows in this system are half-open — they include the start instant and exclude the end instant.

### 2.9. The Billing Ledger and Lifetime Tier Snapshot

Money is represented exclusively in integer cents; there are no fractional-cent fields. Wherever a calculation multiplies by a percentage or a fraction, the product is rounded using the round-half-up method to a whole number of cents, at the point in the formula indicated by the workflow narrative.

Each `Show` maintains `lifetime_billed_cents`, a running sum of the `total_cents` of every invoice finalized for that show. This figure is *increased* by the `total_cents` of each invoice the moment that invoice is issued (whether a per-episode invoice at publish or a retainer-overage invoice at cycle close), and it is *decreased* by an invoice's `total_cents` when that invoice is voided, reversing the original billing. The lifetime figure is more than a report: it selects the late-fee tier, and because each new invoice both *reads* the lifetime figure and *adds to* it, the order of operations is pinned — the tier is chosen from the lifetime snapshot taken **before** the new invoice is added, the late fee and total are computed against that snapshot, and only then is the new total added to `lifetime_billed_cents`. This serialization is what prevents an invoice from inflating the very tier that prices it.

### 2.10. Loudness Conformance

Audio masters are held to the show's integrated loudness target. Each `Show` declares a `target_loudness_lufs` between -23.0 and -12.0 inclusive, defaulting to -16.0 if not supplied at creation. A `MASTER_AUDIO` asset version carries a measured `integrated_loudness_lufs`; for any other deliverable kind that field is null. The conformance rule is that a master's measured integrated loudness must lie within a fixed tolerance of the show's target — that is, the absolute difference between the version's measured loudness and the show's target must not exceed the loudness tolerance. This rule is enforced at two points in the pipeline, described in §3.4 and §3.5, and a violation at either is rejected with `ERR_LOUDNESS_OUT_OF_SPEC`.

### 2.11. Optimistic Concurrency Control

Two transition endpoints are guarded by optimistic concurrency control, because the resources they mutate can have their `version` advanced by unrelated activity between the moment a client reads them and the moment it acts.

Terminating an engagement contract requires the request body to carry `expected_engagementcontract_version`, holding the client's last-observed `version` of the target contract. If that value does not equal the contract's current `version` — because, for instance, an activation or a posture-driven recompute has advanced the contract since the client last read it — the termination is rejected with `ERR_STALE_VERSION` at HTTP 412, so the client cannot terminate against a view it no longer holds.

Reconciling an ad campaign requires the request body to carry `expected_adcampaign_version`, holding the client's last-observed `version` of the target campaign. If that value does not equal the campaign's current `version` — because, for instance, a slot was added or the campaign was approved since the client last read it — the reconciliation is rejected with `ERR_STALE_VERSION` at HTTP 412, so revenue is never settled over a slot set the client never saw.

No other endpoint accepts a version field, and an endpoint not listed here performs no concurrency check.

## 3. Business Logic & Workflows

### 3.1. Onboarding a Show and Its Commercial Engagement

A show is onboarded with a display `title`, a `format` drawn from `INTERVIEW`, `SOLO`, `PANEL`, or `NARRATIVE`, a `billing_model` of either `PER_EPISODE` or `RETAINER`, and an optional mastering `target_loudness_lufs` (see §2.10 for its range and default). At creation the show's `lifetime_billed_cents` is zero, its `open_episode_count` is zero, and its `production_posture` is `SUSPENDED`. The show cannot do creative work until it has a live commercial engagement.

That engagement is an `EngagementContract`, created by a platform operator against a show via `show_id`. The contract declares a `tier` of `STANDARD`, `PRIORITY`, or `RUSH` — which selects SLA hours, base price, and overage rate throughout the system — and an `engagement_type` of `PER_EPISODE` or `RETAINER`. For a retainer engagement, `monthly_included_episodes` states how many episodes the monthly fee covers before overage applies; this value must be at least 0 in general, and strictly greater than 0 only when the engagement type is `RETAINER` (it must be 0 for a per-episode engagement). The contract may carry a `loyalty_discount_pct`, a per-episode subtotal discount fraction between 0.0 and 0.5 inclusive (defaulting to 0.0), which is later capped in cents. A contract also records a system-managed `status` and an `activated_at` timestamp.

A contract is born in `DRAFT`. A platform operator activates it, moving `DRAFT → ACTIVE`, only when it is currently `DRAFT`; activation of a retainer-type contract additionally requires `monthly_included_episodes` to be at least 1. Activation stamps `activated_at` from the logical clock and, because a newly active contract can lift the show out of `SUSPENDED`, recomputes the owning show's posture. From `ACTIVE`, a contract may be expired (`ACTIVE → EXPIRED`) when it is currently `ACTIVE`, or terminated (`ACTIVE → TERMINATED`) when it is currently `ACTIVE`. Termination is the optimistic-concurrency-guarded operation of §2.11: it requires `expected_engagementcontract_version` to match the contract's current `version`, failing with `ERR_STALE_VERSION` (HTTP 412) otherwise. Both expiry and termination recompute the owning show's posture — and since removing the last `ACTIVE` contract leaves no active contract, the posture typically falls to `SUSPENDED`. A transition attempted from a state other than the one each requires is rejected with `ERR_INVALID_STATE`. `EXPIRED` and `TERMINATED` are terminal.

### 3.2. Commissioning Episodes Against an Active Engagement

A `ShowOwner` (or a platform operator) commissions an episode by naming its owning `show_id`, the `contract_id` of the engagement that will bill it, a `title`, the `planned_track_count` of raw audio tracks expected at intake (which must be at least 1), and an optional `transcript_requested` flag (defaulting to false) signalling that a transcript is in scope. Creation is permitted only when the owning show's posture is `ACTIVE`, failing otherwise with `ERR_SHOW_NOT_ACTIVE`; and the named contract must itself be `ACTIVE` and must belong to the same show, failing otherwise with `ERR_CONTRACT_NOT_ACTIVE`. A new episode enters the pipeline in `INTAKE`, and its creation recomputes the show's `open_episode_count` and posture.

The episode's pipeline status moves through `INTAKE`, `RECORDING`, `EDITING`, `REVIEW`, and then either back to `EDITING` on a revision or forward to `MASTERED`, then `SCHEDULED`, then `PUBLISHED`; the side branches `ARCHIVED` and `CANCELLED` are also reachable. The episode additionally carries several system- and computed-managed fields filled in along the way: `recording_ended_at` (set when the recording session completes), `assets_complete_at` (set when raw assets are locked), `turnaround_due_utc` (the editing deadline — provisional at first, then finalized), `delivered_late` (a computed boolean set at approval), `revision_count` (how many times review sent the edit back), and `published_at` (set at publish, and the ordering key for retainer consumption).

An episode may be cancelled by its `ShowOwner` while it is in any of `INTAKE`, `RECORDING`, `EDITING`, or `REVIEW`; a cancel attempt from any other state is rejected with `ERR_INVALID_STATE`. Cancellation moves the episode to `CANCELLED`, cascades any of the episode's still-live sessions (those in `BOOKED` or `LIVE`) to `CANCELLED`, and recomputes the show's `open_episode_count`. Separately, a platform operator may archive an episode that is currently `PUBLISHED`, moving it `PUBLISHED → ARCHIVED` and recomputing `open_episode_count`; archival from any non-`PUBLISHED` state is rejected with `ERR_INVALID_STATE`.

### 3.3. Recording: Sessions, Engineers, and Booking Windows

Recording is performed by an `Engineer`, a roster entity created by a platform operator with a `name`, an optional `remote_buffer_minutes` (the idle buffer this engineer needs between remote sessions for gear reset and upload, defaulting to 30 and required to be at least 0), and an optional `active` flag (defaulting to true) controlling whether the engineer accepts new bookings.

A `ProducerEng` books a recording `Session` against an episode (`episode_id`) and an engineer (`engineer_id`), declaring a `capture_mode` of `STUDIO` or `REMOTE` and a booking window of `scheduled_start_utc` (inclusive) to `scheduled_end_utc` (exclusive). Several gates apply at booking time. The booking window must be well-formed, with the end strictly after the start, or the booking fails with `ERR_INVALID_WINDOW`. The owning show must be `ACTIVE`, or the booking fails with `ERR_SHOW_NOT_ACTIVE`. The chosen engineer must be active, or the booking fails with `ERR_ENGINEER_INACTIVE`. And the window must respect the engineer's capacity, which depends on capture mode:

- For a `STUDIO` booking, the window must not overlap any non-`CANCELLED` `STUDIO` session already held by the same engineer. Overlap is judged on the half-open interval, so two windows that merely touch at an endpoint — one ending exactly where the next begins — are allowed; any true overlap is rejected with `ERR_SESSION_OVERLAP`.
- For a `REMOTE` booking, the new window must be separated from every non-`CANCELLED` `REMOTE` session of the same engineer by at least that engineer's `remote_buffer_minutes`: the start of the later session must be at or after the end of the earlier session plus the buffer. A gap exactly equal to the buffer is allowed; a smaller gap is rejected with `ERR_REMOTE_BUFFER_VIOLATION`.

A new session is born `BOOKED`. The first booked session for an episode is what moves it out of `INTAKE` context, and the session lifecycle then drives the episode pipeline. A `ProducerEng` starts a session (`BOOKED → LIVE`) when it is currently `BOOKED` and its owning episode is in `INTAKE` or `RECORDING`; starting a session whose episode was still in `INTAKE` advances that episode to `RECORDING`. The engineer completes a live session (`LIVE → COMPLETED`) when it is currently `LIVE`; completion stamps the session's `completed_at` from the clock, and bubbles the episode `RECORDING → EDITING`, stamping the episode's `recording_ended_at` from the session's `completed_at` and computing the **provisional** turnaround deadline (see §3.6). Alternatively a booked session may be cancelled (`BOOKED → CANCELLED`) when it is currently `BOOKED`. Any session transition attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

### 3.4. Deliverables, Asset Versions, and the Editing Loop

While an episode is in editing, the `ProducerEng` assembles its deliverables. A `Deliverable` is created against an episode (`episode_id`) with a `kind` of `MASTER_AUDIO`, `SHOW_NOTES`, or `TRANSCRIPT`, and is born `PENDING`. Each deliverable tracks a computed `current_version_no` (the highest accepted version number, initially 0) and progresses `PENDING → READY → DELIVERED`.

Work is delivered as an `AssetVersion` submitted against a deliverable (`deliverable_id`). A version may declare `supersedes_version_id`, the prior accepted version of the *same* deliverable that it replaces (or null for the first version); when supersession is claimed, the referenced version must be an `ACCEPTED` version of the same deliverable, failing otherwise with `ERR_INVALID_SUPERSEDE`. The new version's `version_no` is computed as one greater than the superseded version's number, or 1 when nothing is superseded. For a `MASTER_AUDIO` deliverable the submission carries the measured `integrated_loudness_lufs`; for other kinds that value is null. A submitted version is born `SUBMITTED` and moves to either `ACCEPTED` or `REJECTED`.

Accepting a version (`SUBMITTED → ACCEPTED`) may be done by a `ShowOwner` or a `ProducerEng`; for a `MASTER_AUDIO` version, acceptance enforces loudness conformance (§2.10) — the version's `integrated_loudness_lufs` must lie within the loudness tolerance of the show's `target_loudness_lufs`, failing with `ERR_LOUDNESS_OUT_OF_SPEC`. Acceptance moves the owning deliverable to `READY` and sets the deliverable's `current_version_no` to the accepted version's number. Rejecting a version (`SUBMITTED → REJECTED`) is a `ShowOwner` action. A version transition from the wrong state is rejected with `ERR_INVALID_STATE`.

The episode editing loop runs through review. From `EDITING`, a `ProducerEng` submits the edit (`EDITING → REVIEW`) — but only after the episode's assets have been locked, i.e. `assets_complete_at` is set; submitting before assets are locked is rejected with `ERR_ASSETS_NOT_LOCKED`. From `REVIEW`, the `ShowOwner` either requests a revision (`REVIEW → EDITING`), which increments the episode's `revision_count` by one and re-opens editing — this revision loop may repeat — or approves the edit (`REVIEW → MASTERED`). Approval has preconditions: the episode must be in `REVIEW`; the `MASTER_AUDIO` deliverable for the episode must be `READY`, failing otherwise with `ERR_MASTER_NOT_READY`; and the currently accepted master's loudness must be within tolerance of the show's target, failing otherwise with `ERR_LOUDNESS_OUT_OF_SPEC` (this is the second enforcement point of §2.10). When these hold in this order — state legality first, then master readiness, then the loudness conformance check — approval finalizes the turnaround deadline and sets `delivered_late` (see §3.6), and moves the `MASTER_AUDIO` deliverable to `DELIVERED`. Any of these episode transitions attempted from the wrong state is rejected with `ERR_INVALID_STATE`.

Asset readiness is frozen for billing at a distinct step: a `ProducerEng` locks the episode's raw assets, supplying the actual `raw_track_count`. Locking stamps `assets_complete_at` from the clock and records `raw_track_count` on the episode, and that frozen count is what feeds the final turnaround SLA and the per-episode invoice's extra-track charge.

### 3.5. Scheduling, Publishing, and Per-Episode Billing

Once mastered, an episode is scheduled by a `ProducerEng` (`MASTERED → SCHEDULED`) when it is currently `MASTERED`; if the episode was commissioned with `transcript_requested` set to true, scheduling additionally requires the `TRANSCRIPT` deliverable to be `READY`, failing otherwise with `ERR_TRANSCRIPT_NOT_READY`. Publishing is a `ProducerEng` action (`SCHEDULED → PUBLISHED`) permitted when the episode is currently `SCHEDULED` and the owning show's posture is `ACTIVE` or `ON_HOLD`; a publish while the show is `SUSPENDED` is rejected with `ERR_SHOW_SUSPENDED`. A scheduling or publishing transition from the wrong state is rejected with `ERR_INVALID_STATE`.

Publishing stamps `published_at` from the clock and recomputes the show's `open_episode_count` and posture. For an episode billed under a per-episode contract, publishing also creates and issues an invoice. The invoice's `subtotal_cents` is the sum of three parts: the tier base price keyed on the contract's `tier`, where `STANDARD` is 15000 cents, `PRIORITY` is 22000 cents, and `RUSH` is 35000 cents; plus a transcript charge of 4000 cents when the episode requested a transcript and 0 otherwise; plus an extra-track charge equal to 2500 cents for every track beyond the second, i.e. the frozen `raw_track_count` reduced by an extra-track floor of 2 (never below zero) multiplied by 2500 cents. From that subtotal a loyalty discount is computed: the raw discount is the subtotal multiplied by the contract's `loyalty_discount_pct`, rounded half up to whole cents, and the stored `discount_cents` is that raw discount capped at a maximum of 5000 cents. The late fee is then computed per §3.7, and the invoice's `total_cents` equals the subtotal minus the discount plus the late fee. The invoice records `show_id` and `episode_id` (its `retainer_cycle_id` is null), with `kind` `PER_EPISODE`, and the show's `lifetime_billed_cents` is increased by the invoice's `total_cents`, observing the snapshot ordering of §2.9.

### 3.6. Turnaround Deadlines and Late Delivery

The editing turnaround deadline, `turnaround_due_utc`, is computed twice in an episode's life from the same SLA function but with different inputs. The SLA in hours for a given track count is the tier's base SLA plus a per-track surcharge for multitrack work: the tier base is 72 hours for `STANDARD`, 48 hours for `PRIORITY`, and 24 hours for `RUSH`; the surcharge is 6 hours for each track beyond a multitrack floor of 2 tracks, i.e. the track count reduced by 2 (never below zero) multiplied by 6 hours. There is no rounding — the arithmetic is in whole hours on datetimes.

The **provisional** deadline is computed when the recording session completes and the episode bubbles into editing: it is the episode's `recording_ended_at` plus the SLA hours computed from the intake estimate `planned_track_count`. The **final** deadline is computed when the show owner approves the edit: it is the episode's `assets_complete_at` plus the SLA hours computed from the frozen actual `raw_track_count`. The two can differ whenever the actual track count differs from the planned one or the assets were locked later than recording ended. At approval, `delivered_late` is set to true exactly when the approval-time clock reading is strictly after the final `turnaround_due_utc`, and false otherwise.

### 3.7. Late-Fee Tiers

A late fee is assessed on a per-episode invoice at publish, and on a retainer-overage invoice at cycle close, only when the relevant delivery was late. The fee tier is keyed on the show's `lifetime_billed_cents` *snapshot* — the value before the current invoice is added, per §2.9: the tier is `GOLD` when the snapshot is at least 80000 cents, `SILVER` when the snapshot is at least 40000 cents (but below the gold threshold), and `BRONZE` otherwise. When the delivery was late, `late_fee_cents` is the quantity (subtotal minus discount) multiplied by the tier's late-fee rate — 0.02 for `BRONZE`, 0.035 for `SILVER`, and 0.05 for `GOLD` — rounded half up to whole cents. When the delivery was not late, `late_fee_cents` is 0 regardless of tier. Only after the late fee and the total are computed against the pre-invoice snapshot is the new total added to `lifetime_billed_cents`.

### 3.8. Retainer Cycles and Waterfall Reconciliation

For a retainer engagement, billing is organized into cycles. A platform operator opens a `RetainerCycle` against a contract (`contract_id`) with a half-open window from `cycle_start_utc` (inclusive) to `cycle_end_utc` (exclusive). The window must be well-formed, with the end strictly after the start, or the open fails with `ERR_INVALID_WINDOW`. The new window must not overlap any existing cycle of the *same* contract in any status; overlap is judged on the half-open interval, so touching windows (the earlier cycle's end equal to the later cycle's start) are allowed with no buffer, but any true overlap is rejected with `ERR_CYCLE_OVERLAP`. A cycle is born `OPEN` and progresses `OPEN → CLOSED`. It tracks computed `included_consumed` and `overage_episode_count` (both initially 0) and a `closed_at` timestamp.

Reconciliation distributes the contract's monthly included episodes against actual production, as a waterfall: episodes are ordered chronologically, the included allotment is filled first, and everything beyond it is overage. Concretely, the eligible episodes are those of the contract's show whose `published_at` falls within the cycle's half-open window (at or after the start, before the end), filtered by the variant rule below; the eligible set is then sorted by `published_at` ascending with `created_at` ascending as a tie-break; `included_consumed` is the smaller of the eligible count and the contract's `monthly_included_episodes`; `overage_episode_count` is the eligible count minus `monthly_included_episodes`, never below zero; and the overage subtotal is the overage count multiplied by the tier's overage rate — 12000 cents for `STANDARD`, 16000 cents for `PRIORITY`, and 22000 cents for `RUSH`.

Reconciliation runs in two variants that differ only in which episodes are eligible. The **provisional** variant is a forward-looking projection that does not persist anything: its eligible set includes episodes in `SCHEDULED` or `PUBLISHED` status (a scheduled episode is counted by its intended publish window, using `published_at` when set and otherwise treated as in-window), and it tends to over-count relative to the final figure. The **final** variant runs at cycle close and is authoritative: its eligible set includes only episodes in `PUBLISHED` status with a non-null `published_at` inside the window.

Closing a cycle is a platform-operator action permitted when the cycle is currently `OPEN` and the owning contract's `engagement_type` is `RETAINER` (closing a cycle whose contract is not a retainer is rejected with `ERR_NOT_RETAINER`); a close from a non-`OPEN` cycle is rejected with `ERR_INVALID_STATE`. Closing runs the final reconciliation, persisting `included_consumed` and `overage_episode_count`; when the overage count is greater than zero, it creates and issues a `RETAINER_OVERAGE` invoice (recording `show_id` and `retainer_cycle_id`, with `episode_id` null and `kind` `RETAINER_OVERAGE`) whose subtotal is the overage subtotal above, with discount, late fee, and total computed as for any invoice, and the show's `lifetime_billed_cents` is increased by the invoice's `total_cents` per §2.9. Closing stamps `closed_at` and recomputes the owning show's posture. A projection of the same numbers may be obtained at any time without closing, via the provisional variant, and that read does not persist.

### 3.9. Invoice Administration and Posture Feedback

An `Invoice` is born `ISSUED`. From `ISSUED` it may go to `PAID`, `OVERDUE`, or `DISPUTED`; a `DISPUTED` invoice may later go to `PAID` or `VOID`; an `OVERDUE` invoice may be paid. Each of these is gated on the invoice being in the required prior state, failing otherwise with `ERR_INVALID_STATE`. A `ShowOwner` pays an invoice that is `ISSUED`, `OVERDUE`, or `DISPUTED`, moving it to `PAID`. A `ShowOwner` disputes an `ISSUED` invoice, moving it to `DISPUTED`. A platform operator marks an `ISSUED` invoice `OVERDUE`, and may void a `DISPUTED` invoice, moving it to `VOID`.

Every one of these transitions recomputes the owning show's posture, which is how the commercial gate stays current: marking an invoice overdue typically drops a show to `ON_HOLD`; disputing one drops it to `SUSPENDED`; paying or resolving the last problem invoice can lift it back to `ACTIVE`. Voiding additionally reverses the original billing by decreasing the show's `lifetime_billed_cents` by the voided invoice's `total_cents` before the posture is recomputed. `PAID` and `VOID` are terminal.

### 3.10. Sponsorship: Campaigns, Slots, and Revenue Split

A sponsorship operator creates an `AdCampaign` against a show (`show_id`) with a `sponsor_name` and an optional `platform_fee_pct` — the platform's cut of gross ad revenue, between 0.0 and 0.5 inclusive, defaulting to 0.30 — and the campaign is born `DRAFT`. While the campaign is `DRAFT`, the operator adds one or more `AdSlot` rows, each naming the campaign (`campaign_id`), the episode it is inserted into (`episode_id`), a `placement` of `PRE_ROLL`, `MID_ROLL`, or `POST_ROLL`, and a `gross_cents` revenue figure that must be at least 1. Because adding a slot changes the slot set, each slot addition increments the owning campaign's `version`.

A campaign may be cancelled (`DRAFT → CANCELLED`) while it is `DRAFT`, or approved (`DRAFT → APPROVED`) while it is `DRAFT` and it carries at least one slot — approving a campaign with zero slots is rejected with `ERR_NO_SLOTS`. From `APPROVED`, the operator reconciles the campaign (`APPROVED → RECONCILED`). Reconciliation is the second optimistic-concurrency-guarded operation (§2.11): the request must carry `expected_adcampaign_version` matching the campaign's current `version`, failing otherwise with `ERR_STALE_VERSION` (HTTP 412). Reconciliation further requires every slot's episode to be `PUBLISHED`; if any slot's episode is not yet published the request is rejected with `ERR_SLOT_EPISODE_NOT_PUBLISHED`. A transition from the wrong state is rejected with `ERR_INVALID_STATE`. `RECONCILED` and `CANCELLED` are terminal.

Reconciliation computes the revenue split with the rounding order pinned to per-slot rounding: the show's keep fraction is one minus the campaign's `platform_fee_pct`; `show_payout_cents` is the sum, over every slot, of each slot's `gross_cents` multiplied by the keep fraction and rounded half up to whole cents — rounding each slot individually and only then summing, which differs in cents from summing first and rounding once; the gross total is the sum of every slot's `gross_cents`; and `platform_take_cents` is the gross total minus `show_payout_cents`.

### 3.11. The Logical Clock

The service keeps a logical clock that is the sole source of "now" for every timestamp the system stamps — session completion, asset lock, publish, contract activation, cycle close, and the late-delivery comparison at approval. A platform operator advances the clock by supplying a target instant `to_iso8601`. At startup the clock reads exactly `2026-03-01T00:00:00Z`, and before any clock-setting call it holds that default and never falls back to wall-clock time.

## 4. Endpoint Definitions

Operations that create a new, stand-alone resource return a `201 Created` status code. Operations that modify an existing resource — including all lifecycle transitions and the clock-setting capability — return a `200 OK` status code. All list and single-resource reads return `200 OK`.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/_clock/set_current_utc` | Set the server logical clock | PlatformAdmin |
| POST | `/shows` | Create a show | PlatformAdmin, ShowOwner |
| GET | `/shows` | List shows | PlatformAdmin, ShowOwner, ProducerEng, AdOps |
| GET | `/shows/{id}` | Get a show with computed posture and lifetime fields | PlatformAdmin, ShowOwner, ProducerEng, AdOps |
| POST | `/contracts` | Create an engagement contract (DRAFT) | PlatformAdmin |
| GET | `/contracts` | List contracts; filter by show | PlatformAdmin, ShowOwner |
| GET | `/contracts/{id}` | Get a contract | PlatformAdmin, ShowOwner |
| POST | `/contracts/{id}/activate` | Activate a DRAFT contract | PlatformAdmin |
| POST | `/contracts/{id}/terminate` | Terminate an ACTIVE contract (OCC-guarded) | PlatformAdmin |
| POST | `/contracts/{id}/expire` | Expire an ACTIVE contract | PlatformAdmin |
| POST | `/retainer-cycles` | Open a billing cycle for a retainer contract | PlatformAdmin |
| GET | `/retainer-cycles` | List retainer cycles; filter by contract | PlatformAdmin, ShowOwner |
| GET | `/retainer-cycles/{id}` | Get a retainer cycle | PlatformAdmin, ShowOwner |
| GET | `/retainer-cycles/{id}/projection` | Provisional reconciliation without closing | PlatformAdmin, ShowOwner |
| POST | `/retainer-cycles/{id}/close` | Close a cycle; final reconciliation and overage billing | PlatformAdmin |
| POST | `/engineers` | Create a production engineer | PlatformAdmin |
| GET | `/engineers` | List engineers | PlatformAdmin, ProducerEng |
| GET | `/engineers/{id}` | Get an engineer | PlatformAdmin, ProducerEng |
| POST | `/episodes` | Create an episode (INTAKE) | ShowOwner, PlatformAdmin |
| GET | `/episodes` | List episodes; filter by show or contract | PlatformAdmin, ShowOwner, ProducerEng, AdOps |
| GET | `/episodes/{id}` | Get an episode with computed turnaround and late fields | PlatformAdmin, ShowOwner, ProducerEng, AdOps |
| POST | `/episodes/{id}/lock-assets` | Lock raw assets and freeze the track count | ProducerEng |
| POST | `/episodes/{id}/submit-edit` | Move editing into review | ProducerEng |
| POST | `/episodes/{id}/request-revision` | Send the edit back to editing (revision loop) | ShowOwner |
| POST | `/episodes/{id}/approve-edit` | Approve the edit; finalize turnaround | ShowOwner |
| POST | `/episodes/{id}/schedule` | Move a mastered episode to scheduled | ProducerEng |
| POST | `/episodes/{id}/publish` | Publish a scheduled episode; bill per-episode | ProducerEng |
| POST | `/episodes/{id}/cancel` | Cancel a non-terminal episode | ShowOwner |
| POST | `/episodes/{id}/archive` | Archive a published episode | PlatformAdmin |
| POST | `/sessions` | Book a recording session | ProducerEng |
| GET | `/sessions` | List sessions; filter by episode or engineer | PlatformAdmin, ProducerEng |
| GET | `/sessions/{id}` | Get a session | PlatformAdmin, ProducerEng |
| POST | `/sessions/{id}/start` | Start a booked session | ProducerEng |
| POST | `/sessions/{id}/complete` | Complete a live session; bubble episode to editing | ProducerEng |
| POST | `/sessions/{id}/cancel` | Cancel a booked session | ProducerEng |
| POST | `/deliverables` | Create a deliverable (PENDING) | ProducerEng |
| GET | `/deliverables` | List deliverables; filter by episode | PlatformAdmin, ProducerEng, ShowOwner |
| GET | `/deliverables/{id}` | Get a deliverable | PlatformAdmin, ProducerEng, ShowOwner |
| POST | `/asset-versions` | Submit an asset version (SUBMITTED) | ProducerEng |
| GET | `/asset-versions` | List asset versions; filter by deliverable or superseded version | PlatformAdmin, ProducerEng, ShowOwner |
| GET | `/asset-versions/{id}` | Get a single asset version | PlatformAdmin, ProducerEng, ShowOwner |
| POST | `/asset-versions/{id}/accept` | Accept a submitted version | ShowOwner, ProducerEng |
| POST | `/asset-versions/{id}/reject` | Reject a submitted version | ShowOwner |
| GET | `/invoices` | List invoices; filter by show, episode, or cycle | PlatformAdmin, ShowOwner |
| GET | `/invoices/{id}` | Get an invoice with computed money fields | PlatformAdmin, ShowOwner |
| POST | `/invoices/{id}/pay` | Pay an issued, overdue, or disputed invoice | ShowOwner |
| POST | `/invoices/{id}/mark-overdue` | Mark an issued invoice overdue | PlatformAdmin |
| POST | `/invoices/{id}/dispute` | Dispute an issued invoice | ShowOwner |
| POST | `/invoices/{id}/void` | Void a disputed invoice; reverse billing | PlatformAdmin |
| POST | `/ad-campaigns` | Create an ad campaign (DRAFT) | AdOps |
| GET | `/ad-campaigns` | List ad campaigns; filter by show | PlatformAdmin, AdOps |
| GET | `/ad-campaigns/{id}` | Get an ad campaign with computed splits | PlatformAdmin, AdOps |
| POST | `/ad-campaigns/{id}/approve` | Approve a draft campaign | AdOps |
| POST | `/ad-campaigns/{id}/reconcile` | Reconcile an approved campaign (OCC-guarded) | AdOps |
| POST | `/ad-campaigns/{id}/cancel` | Cancel a draft campaign | AdOps |
| POST | `/ad-slots` | Add an ad slot to a draft campaign | AdOps |
| GET | `/ad-slots` | List ad slots; filter by campaign or episode | PlatformAdmin, AdOps |
| GET | `/ad-slots/{id}` | Get a single ad slot | PlatformAdmin, AdOps |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 Unauthorized |
| `ERR_FORBIDDEN_ROLE` | 403 Forbidden |
| `ERR_NOT_RESOURCE_OWNER` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_INVALID_ENUM` | 422 Unprocessable Entity |
| `ERR_INVALID_PAGINATION` | 400 Bad Request |
| `ERR_INVALID_WINDOW` | 422 Unprocessable Entity |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SHOW_NOT_ACTIVE` | 409 Conflict |
| `ERR_SHOW_SUSPENDED` | 409 Conflict |
| `ERR_CONTRACT_NOT_ACTIVE` | 409 Conflict |
| `ERR_INVALID_SUPERSEDE` | 409 Conflict |
| `ERR_LOUDNESS_OUT_OF_SPEC` | 409 Conflict |
| `ERR_SESSION_OVERLAP` | 409 Conflict |
| `ERR_REMOTE_BUFFER_VIOLATION` | 409 Conflict |
| `ERR_ENGINEER_INACTIVE` | 409 Conflict |
| `ERR_SLOT_EPISODE_NOT_PUBLISHED` | 409 Conflict |
| `ERR_TRANSCRIPT_NOT_READY` | 409 Conflict |
| `ERR_MASTER_NOT_READY` | 409 Conflict |
| `ERR_NOT_RETAINER` | 409 Conflict |
| `ERR_CYCLE_OVERLAP` | 409 Conflict |
| `ERR_ASSETS_NOT_LOCKED` | 409 Conflict |
| `ERR_NO_SLOTS` | 409 Conflict |
