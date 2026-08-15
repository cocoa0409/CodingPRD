# Post-Production Workflow & Dailies Management API — Product Requirements Document

## 1. Introduction

A post-production facility is a choreography of expensive, time-boxed resources. Camera media arrives inside declared ingest windows, proxies must render before editorial can begin, dailies go out to dozens of recipients under strict leak-protection rules, edit bays are booked by the hour, and conform, color, and sound work is handed to outside vendors whose capacity is finite. Alongside the creative flow runs an unforgiving audit trail: every frame of source media must be accounted for, every deliverable must survive quality control with a bounded number of attempts, and at the end of the engagement every retained byte must be sealed to tape with a retention horizon the client can rely on.

This document specifies the API for managing that end-to-end workflow. The system governs media ingest and proxy generation, watermark-gated dailies distribution, edit bay and artist scheduling with editorial version tracking, conform/color/sound turnover with per-revision change lists, review rounds with consolidated notes, deliverable mastering with QC failure remediation, LTO archive with retention accounting, and vendor onboarding with competitive bid tracking. All facility resources are served under the `/post-production` URL prefix. The intended reader is the engineer who will implement the service; every behavioral rule in this document is contractual.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted to invoke the endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403).

The system recognizes nine roles, spelled exactly as follows:

- `PostSupervisor` — owns the project lifecycle (create, activate, wrap, close, archive), watermark profiles, edit bay management, turnover issue/close/void, bid award, and deliverable delivery and rejection.
- `MediaManager` — owns ingest, proxies, storage, and archives: batches and their ingest transitions, asset registration and verification, and archive jobs.
- `DailiesCoordinator` — owns dailies packaging and distribution: creating packages and publishing or revoking them.
- `ConformEditor` — owns conform work: asset conform and lock, turnovers and staging, change lists, deliverable render, and acknowledging or resolving review notes.
- `ReviewerLead` — owns review rounds and note consolidation: opening rounds, closing notes, and approving or rejecting rounds.
- `QCOperator` — owns quality control on deliverables: enqueueing QC and appending QC reports.
- `FacilityAdmin` — owns vendors (onboard, suspend, reinstate, offboard) and the facility's logical clock.
- `VendorRep` — an external vendor representative who submits and withdraws bids and acknowledges and returns turnovers for their own vendor.
- `Artist` — books edit bays, checks in, and completes or cancels their own bookings.

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `VendorRep`, `X-User-ID` is the `id` of the acting `Vendor`; ownership checks on any resource that references a vendor — a bid's `vendor_id`, an awarded turnover's `vendor_id` — compare that foreign-key field to `X-User-ID`, and a `VendorRep` may act only on records belonging to their own vendor. When `X-User-Role` is any of `PostSupervisor`, `MediaManager`, `DailiesCoordinator`, `ConformEditor`, `ReviewerLead`, `QCOperator`, `FacilityAdmin`, or `Artist`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `issued_by` on a QC report, where it captures the issuing operator's `X-User-ID`) but does not compare it to any entity's `id`. One business-level exception exists for `Artist`: booking check-in, completion, and artist-initiated cancellation compare `X-User-ID` against the booking's `artist_email` as a domain rule (see §3.4), not as an entity-identity mapping.

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

Endpoints that return lists of resources are paginated via two query parameters. The `limit` parameter specifies the maximum number of items to return; when omitted it defaults to 10, and it is bounded below by 1 and above by 100. The `offset` parameter specifies how many items to skip and defaults to 0.

Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp (`created_at`) in ascending order.

List responses carry the pagination fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Facility Logical Clock

All time-dependent behavior in the system reads a single server-side logical clock, never the real wall clock. Before the clock has ever been set, it reads exactly 2026-08-01T00:00:00Z, and it must not fall back to wall-clock time under any circumstance. Every datetime-dependent rule in this document — the ingest-window check on batch ingest start, the booking session-date and hour checks, the no-show sweep, the `published_at`, `revoked_at`, and `sealed_at` stamps, and the retention-horizon computation — takes "now" from this logical clock.

A `FacilityAdmin`-only test-driving capability advances the logical clock to a supplied `to_iso8601` instant and responds with the clock's new reading in `current_utc`. Advancing the clock is not inert: it triggers the no-show sweep, under which any booking still in `RESERVED` whose `session_date` has arrived and whose `end_hour` has passed without a check-in transitions to `NO_SHOW`, and it fires any other time-dependent automatic transitions described in §3.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification; it refreshes on any change to the resource.
- `version` (integer): a system-managed integer that increments by one on every modification to the resource, including modifications caused by recomputed derived fields and cascade side effects.

The sole exception is the QC report. A `QCReport` is an immutable, append-once record: it carries `id` and `created_at` only, and both `updated_at` and `version` are absent from it. Every other entity in this document — projects, batches, assets, watermark profiles, dailies packages, edit bays, bookings, turnover packages, change lists, review rounds, review notes, deliverables, archive jobs, vendors, and vendor bids — carries all four common fields.

### 2.6. Nested Resource Retrieval and Reverse Reachability

Most resources are project-scoped and are addressed through hierarchical paths beneath their project. When an endpoint path contains multiple resource identifiers, the system validates them sequentially from left to right and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing entity; later segments are not examined. The same rule applies to foreign-key fields supplied in a request body — a `batch_id`, `turnover_id`, `round_id`, or similar reference that does not resolve is likewise `ERR_NOT_FOUND`.

In addition to the hierarchical paths, every project-scoped resource is retrievable by its bare `id` through a flat single-resource alias (for example, a batch by `id` without naming its project), and every foreign-key relationship has a reverse collection endpoint that lists the children referencing a given parent — assets or dailies packages of a batch, QC reports of an asset, dailies packages of a watermark profile, bookings of a bay, change lists or vendor bids of a turnover, notes of a review round, QC reports of a deliverable, and turnovers or bids of a vendor. These read paths exist so that a client holding only a child reference can navigate upward and outward; they share the filters and authorization of their hierarchical counterparts. §4 lists both forms.

### 2.7. Optimistic Concurrency Control

Three write operations are guarded by optimistic concurrency control, each against a designated parent entity. On each of these three endpoints the named version field is a mandatory, non-optional input:

- Creating a booking requires `expected_bay_version`, carrying the client's last-observed `version` of the target edit bay. If the bay's current `version` has advanced beyond what the client observed — for example because another writer has since booked against the bay, or the bay has been placed into maintenance — the create is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a stale view of bay availability.
- Applying a change list requires `expected_turnover_version`, carrying the client's last-observed `version` of the parent turnover package. If the turnover's `version` has advanced — for example because a competing change list was applied in the meantime, which would have transitioned this list to `SUPERSEDED` through the side-effect chain — the apply is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Triggering a deliverable render requires `expected_project_version`, carrying the client's last-observed `version` of the project. Because `conform_ready` lives on the project and flips as a side effect of asset locks, change-list applications, and review approvals, a render issued against a stale project snapshot risks launching on a superseded readiness evaluation; it is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these three accepts or requires a version field in its request body.

### 2.8. Units, Precision, and Rounding

Storage accounting is kept in bytes on each asset and is surfaced in gibibytes on the project: byte sums are converted by dividing by 1,073,741,824 (that is, 1024 cubed) and the result is rounded half-up to exactly 3 decimal places. All percentages in the system — proxy progress, bay utilization, vendor load — are integers produced by rounding the exact quotient down to a whole number. Frame counts and frame deltas are integers. Monetary amounts (vendor day rates, bid amounts) are integers denominated in cents. Retention arithmetic treats every year as a fixed 365-day year; leap days are never added. All timestamps are ISO 8601 UTC with three fractional digits.

### 2.9. Validation Order of Evaluation

Every request passes through a fixed validation pipeline, and the ordering is contractual: when several of these checks could fail for the same request, the check earliest in this order produces the error returned.

1. **Authentication.** `X-User-Role` must be present and equal to one of the nine declared roles, and `X-User-ID` must be present; otherwise the request fails with `ERR_UNAUTHENTICATED` (HTTP 401). This check applies to every endpoint.
2. **Authorization.** The declared role must be permitted for the endpoint per the role table in §4; otherwise `ERR_FORBIDDEN` (HTTP 403). Applies to every endpoint.
3. **Existence.** Every path-templated identifier must resolve to an existing entity, validated left to right, and every foreign-key field in the body must resolve; otherwise `ERR_NOT_FOUND` (HTTP 404). Applies to every endpoint.
4. **Body shape.** Required fields must be present, types must match, enum values must be members of their declared enumerations, and numeric ranges must be respected; otherwise `ERR_INVALID_REQUEST` (HTTP 400). Applies to every endpoint.
5. **Stale-version guard.** On the three OCC-guarded writes of §2.7, the supplied expected-version field must equal the parent entity's current `version`; otherwise `ERR_STALE_VERSION` (HTTP 412). Applies to booking creation, change-list application, and deliverable render.
6. **From-state.** The target resource must currently be in the from-state required by the requested transition; otherwise `ERR_INVALID_STATE` (HTTP 409). Applies to every state-transition endpoint. A transition attempted on a resource that has already reached a terminal state of its lifecycle is instead reported as `ERR_ALREADY_TERMINAL` (HTTP 409).
7. **Temporal windows.** Ingest start must fall inside the batch's declared ingest window; a booking's session date must be the present day or a future day; check-in must occur within the booked date and hour interval. Violations yield `ERR_WINDOW_CLOSED` (HTTP 422). Applies to ingest start, booking creation, and booking check-in.
8. **Booking overlap.** The requested half-open hour interval must not overlap an existing non-terminal booking for the same bay on the same date; otherwise `ERR_BOOKING_OVERLAP` (HTTP 409). Applies to booking creation, and is evaluated only after the temporal-window check.
9. **Watermark compliance.** The referenced watermark profile must be `ACTIVE` and must satisfy the project's security-tier gate; otherwise `ERR_WATERMARK_NONCOMPLIANT` (HTTP 422). Applies to dailies publish, and is evaluated before the distribution check.
10. **Distribution validity.** The package's `distribution_list` must be non-empty with unique lowercase addresses, and the referenced batch must be `READY`; otherwise `ERR_DISTRIBUTION_INVALID` (HTTP 422). Applies to dailies publish.
11. **Asset uniqueness.** The composite of project, reel, and clip must be unique among non-purged assets; otherwise `ERR_DUPLICATE_ASSET` (HTTP 409). Applies to asset registration.
12. **Vendor eligibility.** At bid award, the vendor must be `ONBOARDED` and its capabilities must cover the turnover's kind; otherwise `ERR_VENDOR_INELIGIBLE` (HTTP 422).
13. **Vendor capacity.** At turnover issue, the vendor's concurrent in-flight turnovers must be below its slot capacity; otherwise `ERR_VENDOR_CAPACITY_EXCEEDED` (HTTP 422).
14. **Storage quota.** Registering an asset must not push the project's storage usage past its quota; otherwise `ERR_STORAGE_QUOTA_EXCEEDED` (HTTP 422). Applies to asset registration, evaluated after the uniqueness check.
15. **QC rejection threshold.** Rejecting a deliverable requires at least three recorded QC attempts; otherwise `ERR_QC_THRESHOLD_NOT_MET` (HTTP 422).
16. **QC attempts remaining.** Re-rendering a QC-failed deliverable requires fewer than three recorded attempts; otherwise `ERR_QC_ATTEMPTS_EXHAUSTED` (HTTP 422). Applies to deliverable render.
17. **Conformability.** Applying a change list requires every referenced asset to be in a conformable state; otherwise `ERR_ASSET_NOT_CONFORMABLE` (HTTP 422).
18. **Artist identity.** Check-in, completion, and artist-initiated cancellation require the caller's `X-User-ID` to match the booking's `artist_email` compared case-insensitively; otherwise `ERR_ARTIST_MISMATCH` (HTTP 403).
19. **Bay occupancy.** Maintenance and decommissioning require no blocking forward bookings; otherwise `ERR_BAY_OCCUPIED` (HTTP 409).
20. **Project wrappability.** The project wrap, close, and archive preconditions are enforced last; failures yield `ERR_PROJECT_NOT_WRAPPABLE` (HTTP 422).

### 2.10. Derived Fields and Hierarchical Consistency

Many fields in this document are server-computed rather than client-supplied: storage usage on the project, proxy progress on the batch, note counters on the review round, QC attempt counts on the deliverable, and similar. Such fields are recomputed at the moments §3 names for each of them, and a recomputation that changes a parent resource is a mutation of that parent — it refreshes `updated_at` and increments `version`, exactly as a direct edit would. Cascades work the same way: when a parent transition renders children non-operational (a revoked dailies package voiding its review rounds, a purged batch purging its assets, a project wrap revoking every published package), the server performs those transitions automatically, without requiring a client request on each child, and each affected resource is mutated individually. These automatic reconciliations keep the hierarchy aligned at all times; the consistency model is immediate, with no deferred or eventual settlement.

## 3. Business Logic & Workflows

### 3.1. Project Setup and Activation

Everything in the facility happens inside a **Project**. A `PostSupervisor` opens one by supplying a working `title`, a `client_code` for billing (three to eight uppercase alphanumeric characters), the project's base frame rate `fps` (one of 23.976, 24, 25, 29.97, or 30), the master raster dimensions `resolution_width` and `resolution_height` in pixels (1920, 3840, and 4096 are typical widths), an online `storage_quota_gb` expressed in gibibytes, and a `security_tier` of `STANDARD`, `ELEVATED`, or `LOCKDOWN` that governs how strictly dailies watermarking is enforced. Every child record created under the project — batches, assets, profiles, packages, bays, bookings, turnovers, change lists, rounds, notes, deliverables, QC reports, archive jobs, bids — carries the project's `id` as its `project_id`.

A new project begins in `SETUP` with `storage_used_gb` at zero, `open_change_list_count` at zero, and `conform_ready` false. Its full lifecycle is `SETUP` → `ACTIVE` → `WRAPPING` → `CLOSED` → `ARCHIVED`, with `ARCHIVED` terminal. Activation is the gate into real work: a `PostSupervisor` may move a project from `SETUP` to `ACTIVE` only once the project has at least one edit bay in `AVAILABLE` status and at least one watermark profile in `ACTIVE` status — the facility will not open a project that has nowhere to edit and no compliant way to distribute dailies. A successful activation increments the project's `version`. The project list can be filtered by `status` and `security_tier`.

The `conform_ready` flag deserves early introduction because so much later work hangs off it. It is a computed boolean, true exactly when all three of the following hold: no media asset of the project is in a status other than `CONFORMED`, `LOCKED`, or `PURGED`; no review round of the project has `unresolved_critical` set true; and at least one turnover package of the project has reached `ISSUED` or a later state (`ACKED`, `RETURNED`, or `CLOSED`). The flag is recomputed whenever an asset is locked, a change list is applied or rejected, a review round is approved or rejected, or a turnover is issued. The wrap, close, and archive ends of the lifecycle are deferred to §3.8, after the workflows they depend on have been introduced.

### 3.2. Media Ingest, Proxy Generation, and Storage Accounting

Raw camera media enters the facility through a **MediaBatch**. A `MediaManager` declares a batch with a human `batch_label` that is unique within the project (for example "DAY03-CAM_A") and a declared ingest window bounded by `ingest_window_start` and `ingest_window_end`, both ISO 8601 UTC datetimes, where the end must be strictly later than the start. A declared batch sits in `DECLARED` until ingest begins; its lifecycle is `DECLARED` → `INGESTING` → `PROXYING` → `READY`, with `FAILED` reachable from either `INGESTING` or `PROXYING` and `PURGED` as a second terminal state alongside `READY`.

Starting ingest moves the batch from `DECLARED` to `INGESTING` and is permitted only while the project is `ACTIVE` and the logical clock reads a moment inside the declared window, both endpoints inclusive; an attempt outside the window is rejected with `ERR_WINDOW_CLOSED`, and an attempt on a project that is not `ACTIVE` fails as an invalid state transition.

Assets are registered into the batch while it ingests. A `MediaManager` registers a **MediaAsset** with the `batch_id` it belongs to, a `reel_name` identifying the camera reel or card (for example "A001C002"), a `clip_name` identifying the clip, the `source_bytes` size of the source media in bytes (greater than zero), and the clip's `duration_frames` in project frames (greater than zero). The composite of project, `reel_name`, and `clip_name` must be unique among the project's assets that have not been purged; a duplicate is rejected with `ERR_DUPLICATE_ASSET`. Registration is also where the storage quota bites: the project's current storage usage plus the incoming asset's bytes must remain at or below `storage_quota_gb`, or the registration is rejected with `ERR_STORAGE_QUOTA_EXCEEDED`. This comparison is computed on exact byte counts — the sum, over the project's assets that have not been purged, of each asset's `source_bytes` plus its `proxy_bytes`, plus the incoming asset's `source_bytes`, compared against `storage_quota_gb` converted to bytes at 1,073,741,824 bytes per gibibyte — and is never performed on the rounded `storage_used_gb` surface figure, so usage that merely rounds down to the quota still rejects a further sub-threshold addition. A registered asset starts in `INGESTED` with `proxy_status` `PENDING` and `proxy_bytes` zero; the batch's `asset_count` and the project's `storage_used_gb` are recomputed immediately.

Finishing ingest moves the batch from `INGESTING` to `PROXYING`, provided the batch holds at least one asset and its `failed_asset_count` is zero — a batch containing any failed asset cannot advance. The transition flips every asset in the batch from `proxy_status` `PENDING` to `RUNNING`. Proxy completion is then driven per asset: a `MediaManager` marks each proxy complete through a test-driving hook that supplies the rendered `proxy_bytes`, setting the asset's `proxy_status` to `DONE` and recomputing the batch's `proxy_progress_pct`. When the last outstanding asset in the batch reaches `DONE`, the batch automatically transitions from `PROXYING` to `READY` and the project's `storage_used_gb` is recomputed.

Two computed fields keep operators honest during this phase. The batch's `proxy_progress_pct` is the whole-number floor of one hundred times the number of assets in the batch whose `proxy_status` is `DONE`, divided by the batch's `asset_count` — except that the divisor is treated as one when the batch is empty, so the division never fails. The project's `storage_used_gb` is the sum, over every asset of the project whose status is not `PURGED`, of each asset's `source_bytes` plus its `proxy_bytes`, converted to gibibytes and rounded half-up to three decimal places as specified in §2.8. The figure has two natural variants: a provisional reading computed during ingest, while proxies are still rendering and `proxy_bytes` is still zero, which therefore reflects source media only; and the final reading, reached once the batch is `READY` or after a purge, which includes the proxy bytes of completed assets. It is recomputed on asset creation, on each proxy completion, and on batch purge. Each batch also exposes `asset_count` and `failed_asset_count` — the number of its assets, and the number of those in `FAILED` — and the asset list can be filtered by `batch_id`, `status`, and `proxy_status`.

Failures propagate upward. If a checksum mismatch is detected during ingest, the affected asset moves from `INGESTED` to `FAILED` and its parent batch moves to `FAILED` with it; the `MediaManager` is alerted and the batch must be re-declared. A proxy render crash does the same from `VERIFIED`: the asset becomes `FAILED` and the parent batch follows. A `FAILED` batch may be purged unconditionally; a `READY` batch may be purged only when no `PUBLISHED` dailies package references it and no `OPEN` change-list entry references any asset in it. Purging from either state moves the batch to `PURGED`, transitions every child asset to `PURGED`, and recomputes the project's `storage_used_gb`. Purged is terminal for both entities.

Once a proxy is `DONE`, a `MediaManager` verifies the asset, moving it from `INGESTED` to `VERIFIED`; verification is refused while the proxy is incomplete. Verification is the hand-off point to editorial: the conform and lock steps that follow are part of the turnover workflow and are covered in §3.5. The asset's full lifecycle is `INGESTED` → `VERIFIED` → `CONFORMED` → `LOCKED`, with `FAILED` and `PURGED` as the failure and disposal exits and `LOCKED` and `PURGED` as its terminal states. Two further asset fields matter downstream: `qc_fail_count`, the number of QC reports with verdict `FAIL` that name the asset, and `retained_until`, the asset's retention horizon, which stays null until an archive job seals the asset into scope (§3.8).

### 3.3. Watermark Governance and Dailies Distribution

Dailies are the facility's most leak-prone artifact, so distribution is gated by an explicit watermark policy. A `PostSupervisor` authors a **WatermarkProfile** with a `profile_name` unique within the project, an `opacity_pct` between 1 and 100, a `position` of `TOP_LEFT`, `TOP_RIGHT`, `BOTTOM_LEFT`, `BOTTOM_RIGHT`, `CENTER`, or `DIAGONAL_TILE`, an `includes_recipient_email` flag that burns the recipient's email into the visible watermark, and a `forensic_enabled` flag that embeds an invisible forensic payload. A profile begins in `DRAFT`, is promoted to `ACTIVE` by a `PostSupervisor`, and is eventually moved to `RETIRED`, which is terminal. Activation carries a tier-conditioned rule: when the project's `security_tier` is `LOCKDOWN`, the profile must have `forensic_enabled` true and an `opacity_pct` of at least 20, or the activation is refused. Retirement is refused while any `PUBLISHED` dailies package references the profile — live distribution pins the policy. The profile list can be filtered by `status`.

At publish time the profile is scored for compliance. The score starts at zero and accumulates: fifty points if `forensic_enabled` is true; the smaller of forty and the integer half of `opacity_pct` (that is, the opacity divided by two with any fractional half discarded), contributing between zero and forty points; ten points if `includes_recipient_email` is true; and a further ten-point bonus if `position` is `DIAGONAL_TILE`. The total is then capped at one hundred. The project's `security_tier` sets the gate a publish must clear: under `STANDARD` the score must be at least 40; under `ELEVATED` the score must be at least 60 and `includes_recipient_email` must be true; under `LOCKDOWN` the score must be at least 90 and `forensic_enabled` must be true. A profile that is not `ACTIVE`, or whose score fails the tier gate, causes the publish to be rejected with `ERR_WATERMARK_NONCOMPLIANT`.

A **DailiesPackage** is assembled by a `DailiesCoordinator` from three inputs: the `batch_id` of the batch being distributed, the `watermark_profile_id` of the governing profile, and a `distribution_list` of recipient emails — between 1 and 50 entries, all unique, all lowercase. The package is created in `DRAFT`; its `recipient_count` is computed as the length of the distribution list. Publishing moves it from `DRAFT` to `PUBLISHED` and is the most heavily guarded transition in the dailies flow: the project must be `ACTIVE`, the referenced batch must be `READY`, the referenced profile must be `ACTIVE` and pass the tier gate above, and the distribution list must be valid — a list that is empty, contains duplicates, or contains a non-lowercase address, or a reference to a batch that is not `READY`, is rejected with `ERR_DISTRIBUTION_INVALID`. The watermark gate is evaluated before the distribution checks, so a non-compliant profile surfaces as `ERR_WATERMARK_NONCOMPLIANT` rather than being masked by a later failure. A successful publish stamps `published_at` from the logical clock; `revoked_at` stays null.

Revocation closes the distribution window. A `DailiesCoordinator` may revoke a `PUBLISHED` package, and the same transition fires automatically for every published package when the project wraps (§3.8). Either way the package moves to `REVOKED` — its terminal state — `revoked_at` is set from the logical clock, and every review round still `OPEN` whose `target_ref_id` names the package transitions to `VOID`, which in turn voids that round's `OPEN` notes (§3.6). Packages can be listed with `batch_id` and `status` filters, and both the batch side and the profile side expose reverse listings of the packages that reference them.

### 3.4. Edit Bays and Artist Bookings

Editorial capacity is managed room by room. A `PostSupervisor` registers an **EditBay** with a `bay_name` unique within the project (for example "BAY-07"), a `bay_type` of `OFFLINE`, `ONLINE`, `COLOR`, `SOUND`, or `QC`, and a `capacity_hours_per_day` between 1 and 24. A bay starts `AVAILABLE`. A `PostSupervisor` may move it to `MAINTENANCE` only when the bay has no booking in `RESERVED` or `CHECKED_IN` on or after the current logical date; a violating request is rejected with `ERR_BAY_OCCUPIED`. Release returns a `MAINTENANCE` bay to `AVAILABLE` without preconditions. Decommissioning is the terminal exit: from `AVAILABLE` it requires that the bay have no booking in `RESERVED` or `CHECKED_IN` at all, and it cancels every future-dated `RESERVED` booking for the bay as a side effect; from `MAINTENANCE` it requires nothing. A `DECOMMISSIONED` bay never returns. The bay list can be filtered by `status` and `bay_type`.

A **Booking** reserves a bay for an artist on a calendar date. Either a `PostSupervisor` or an `Artist` may create one, supplying the `bay_id`, the `artist_email` (lowercase), the `session_date` in year-month-day form, a `start_hour` between 0 and 23 inclusive, an `end_hour` between 1 and 24 that must be strictly greater than `start_hour`, and a `version_tag` labeling the editorial version booked (for example "v014"), which becomes immutable once the booking is checked in. Because bay availability shifts under competing writers, creation is OCC-guarded per §2.7: the request must carry `expected_bay_version`, and a mismatch with the bay's current `version` is rejected with `ERR_STALE_VERSION`. The booking's `session_date` must be the current logical date or a future one — a past date is rejected with `ERR_WINDOW_CLOSED`. The requested hour interval is then checked against every existing non-terminal booking of the same bay on the same date under half-open semantics: intervals that merely touch, where one's `end_hour` equals the other's `start_hour`, do not conflict, while any true overlap is rejected with `ERR_BOOKING_OVERLAP`. A created booking starts in `RESERVED` with `booked_hours` computed as `end_hour` minus `start_hour`; the bay's `version` increments by one and the bay's utilization for that date is recomputed.

On the day itself, the booked `Artist` checks in: the booking moves from `RESERVED` to `CHECKED_IN` only when `session_date` equals the current logical date and the current logical hour is at least `start_hour` and before `end_hour` — an early or late arrival is rejected with `ERR_WINDOW_CLOSED` — and only when the caller's `X-User-ID` matches the booking's `artist_email` under case-insensitive comparison, failing which the request is rejected with `ERR_ARTIST_MISMATCH`. Completion moves a `CHECKED_IN` booking to `COMPLETED` under the same artist-identity rule. Cancellation moves a `RESERVED` booking to `CANCELLED`: a `PostSupervisor` may cancel any reserved booking, while an `Artist` may cancel only their own booking and only while its `session_date` lies strictly after the current logical date — an identity mismatch is `ERR_ARTIST_MISMATCH`, and an artist attempting to cancel a booking whose date has arrived or passed is refused as an invalid state transition. If the logical clock reaches a booking's `session_date` and passes its `end_hour` with no check-in recorded, the system sweeps the booking to `NO_SHOW`. `COMPLETED`, `CANCELLED`, and `NO_SHOW` are terminal.

Utilization is exposed as a computed read per bay and date. For a given bay and `session_date`, the booked hours are the sum of `booked_hours` over that bay's bookings on that date whose status is `RESERVED`, `CHECKED_IN`, or `COMPLETED`, and the utilization percentage is the whole-number floor of one hundred times the booked hours divided by the bay's `capacity_hours_per_day`. Every booking lifecycle event — creation, check-in, completion, cancellation, and the no-show sweep — recomputes this figure for the affected bay and date. The read returns `session_date`, `booked_hours`, `capacity_hours_per_day`, and `utilization_pct`, accepts an optional `session_date` filter, and when emitting per-day rollups processes bookings ordered by session date ascending, then start hour ascending, then creation timestamp ascending. The booking list can be filtered by `bay_id`, `session_date`, and `status`, and the bay side offers a reverse listing of its bookings with `session_date` and `status` filters.

### 3.5. Turnovers, Vendor Allocation, and Change Lists

Conform, color, and sound work leaves the building through a competitive vendor process. A `FacilityAdmin` onboards a **Vendor** with a `vendor_name` unique across the facility, a `capabilities` list of one to five unique entries drawn from `CONFORM`, `COLOR`, `SOUND`, `QC`, and `ARCHIVE`, a `day_rate_cents` of zero or more, and a `capacity_slots` ceiling between 1 and 20 on concurrently awarded turnovers. A vendor starts `ONBOARDED`. Suspension moves it to `SUSPENDED` and, as a side effect, expires every bid it still has in `SUBMITTED`, transitioning those bids to `EXPIRED`. Reinstatement returns a suspended vendor to `ONBOARDED`. Offboarding moves a `SUSPENDED` vendor to `OFFBOARDED` — terminal — and is permitted only when no turnover package references the vendor in `ISSUED`, `ACKED`, or `RETURNED`. The vendor list can be filtered by `status`.

A **TurnoverPackage** represents one hand-off of a sequence to an outside house. A `ConformEditor` creates one with a `turnover_kind` of `CONFORM`, `COLOR`, or `SOUND` and a `sequence_label` unique within the project for that kind; the package starts in `DRAFT` with `vendor_id` unassigned until a bid is awarded, `issued_at` null, and `change_list_revision` at zero — the field tracks the highest change-list `revision` attached to the turnover and stays zero while none exist. Staging moves the package from `DRAFT` to `STAGED`: the project must be `ACTIVE`, and a `CONFORM` turnover additionally requires at least one project asset in `VERIFIED` or `CONFORMED` so there is something to conform.

Staging is also where assets and turnovers interlock. A `ConformEditor` conforms an asset — moving it from `VERIFIED` to `CONFORMED` — only while the project is `ACTIVE` and the asset is referenced by at least one `CONFORM` turnover in `STAGED` or `ISSUED`. Locking moves a `CONFORMED` asset to `LOCKED` once every change list referencing it has reached `APPLIED`, `SUPERSEDED`, or `REJECTED`, and each lock recomputes the project's `conform_ready`. A `LOCKED` asset is terminal and beyond further editorial change.

With the package `STAGED`, vendors compete. Bid submission is accepted only while the turnover is `STAGED`: a submission against a turnover in any other non-terminal state (`DRAFT`, `ISSUED`, `ACKED`, or `RETURNED`) is rejected with `ERR_INVALID_STATE`, and a submission against a turnover that has reached a terminal state (`CLOSED` or `VOID`) is rejected with `ERR_ALREADY_TERMINAL`, per the from-state rule of §2.9. A `VendorRep` submits a **VendorBid** carrying the `turnover_id`, their own `vendor_id` — which must equal their `X-User-ID`, since a representative acts only for their own vendor — a `bid_amount_cents` greater than zero, and an `eta_days` promise between 1 and 60. A bid starts `SUBMITTED`. Awarding is a `PostSupervisor` decision with four preconditions: the parent turnover must be `STAGED`, no other bid for the turnover may already be `AWARDED`, the vendor must be `ONBOARDED`, and the vendor's `capabilities` must contain the turnover's `turnover_kind` — a vendor lacking the capability or not onboarded is rejected with `ERR_VENDOR_INELIGIBLE`. A successful award transitions the winning bid to `AWARDED`, transitions every other `SUBMITTED` bid for the same turnover to `REJECTED`, and writes the winning bid's vendor into the turnover's `vendor_id`. A `VendorRep` may also withdraw their own `SUBMITTED` bid, moving it to `WITHDRAWN`. Two system events terminate bids without any caller: a competing award rejects the losers, and a turnover void or vendor suspension expires every still-`SUBMITTED` bid. `AWARDED`, `REJECTED`, `EXPIRED`, and `WITHDRAWN` are all terminal.

Issuing the work is a `PostSupervisor` action that moves the turnover from `STAGED` to `ISSUED`. Three conditions must hold: a bid for the turnover exists in `AWARDED`, the turnover's `vendor_id` equals the awarded bid's vendor, and the awarded vendor's `capacity_slots` is not exceeded by its concurrent in-flight turnovers — a vendor already at capacity is rejected with `ERR_VENDOR_CAPACITY_EXCEEDED`. Issuing stamps `issued_at` from the logical clock and recomputes the vendor's load. The vendor then acknowledges the work, moving the turnover from `ISSUED` to `ACKED`; acknowledgment is a `VendorRep` action permitted only when the caller's vendor identity matches the turnover's `vendor_id`, and it likewise recomputes the vendor's load. Returning the finished work — again a `VendorRep` action on their own turnover — moves the package from `ACKED` to `RETURNED`, is permitted only while no change list on the turnover is `OPEN`, and automatically creates a review round with `target_kind` `VENDOR_RETURN` for the returned package. Closing, a `PostSupervisor` action, moves the package from `RETURNED` to `CLOSED` once that auto-created round has reached `APPROVED` or `VOID`, and releases the vendor's capacity slot. A `DRAFT` turnover may instead be voided by a `PostSupervisor`: the package goes to `VOID`, every `SUBMITTED` bid against it transitions to `EXPIRED`, and an `AWARDED` bid, if one exists, transitions to `REJECTED` with the vendor's slot released. `CLOSED` and `VOID` are terminal.

Vendor load is a first-class number, recomputed on bid award, turnover issue, acknowledgment, close, and void, and on vendor suspension. The in-flight load counts the vendor's turnover packages in `ISSUED` and `ACKED`; the utilization percentage is the whole-number floor of one hundred times that load divided by `capacity_slots`. The figure has a provisional variant used at award-evaluation time — before the turnover has been issued, acknowledgment cannot yet be observed, so only `ISSUED` turnovers count — and a steady variant used once turnovers have moved to `ACKED` or beyond, counting `ISSUED` and `ACKED` together. The computed read on a vendor returns `vendor_id`, `in_flight_count`, `capacity_slots`, and `utilization_pct`.

Creative changes after issuance arrive as a **ChangeList**. A `ConformEditor` creates one against a turnover by supplying its `turnover_id` and a list of `entries`, where each entry names an `asset_id`, an `operation` of `ADD`, `DELETE`, `TRIM`, or `SLIP`, and a `frames_delta`. The list's `revision` is a per-turnover monotone integer starting at 1, and its `net_frames_delta` is computed at creation as the sum over all entries of each `frames_delta` taken positively for `ADD` and `SLIP` operations and negatively for `TRIM` and `DELETE` operations. A new list starts `OPEN`, and the project's `open_change_list_count` — the count of its change lists still in `OPEN` status — is recomputed. Applying a list is a `ConformEditor` action guarded by OCC per §2.7: the request must carry `expected_turnover_version` matching the turnover's current `version`, with a mismatch rejected as `ERR_STALE_VERSION`. The parent turnover must be `ISSUED` or `ACKED`, and every entry's `asset_id` must resolve to an asset in `VERIFIED`, `CONFORMED`, or `LOCKED` — any other asset is rejected with `ERR_ASSET_NOT_CONFORMABLE`. A successful apply moves the list to `APPLIED` and performs a chain of side effects: for each `TRIM` or `DELETE` entry the referenced asset's `duration_frames` is adjusted by the entry's `frames_delta` (a `DELETE` operation reduces the asset's duration contribution to zero within this turnover's scope); every other change list on the same turnover still `OPEN` transitions to `SUPERSEDED`, a state the lifecycle never exits; the turnover's `version` increments by one; the project's `conform_ready` is recomputed; and, through the supersession cascade, the project's `open_change_list_count` is recomputed. A `ConformEditor` may instead reject an `OPEN` list outright, moving it to `REJECTED` and recomputing `open_change_list_count`. `APPLIED` and `REJECTED` are terminal. Change lists can be listed with `turnover_id` and `status` filters, and the turnover side exposes the reverse listing of its lists and of its bids.

### 3.6. Review Rounds and Note Consolidation

Review is organized into rounds against a single target. A `ReviewerLead` opens a **ReviewRound** with a `round_label` unique within the project (for example "RR-03"), a `target_kind` of `DAILIES`, `CUT`, `VENDOR_RETURN`, or `DELIVERABLE`, and a `target_ref_id` naming the dailies package, turnover package, or deliverable under review — a reference that does not resolve is `ERR_NOT_FOUND`. The round opens in `OPEN`; `APPROVED`, `REJECTED`, and `VOID` are its terminal states.

Notes accumulate inside the round. A `ReviewerLead`, `ConformEditor`, or `PostSupervisor` adds a **ReviewNote** with the parent `round_id`, an `author_email` in lowercase, a `severity` of `INFO`, `MINOR`, `MAJOR`, or `CRITICAL`, and a `body` of free text between 1 and 2000 characters. A note starts `OPEN`; `RESOLVED` and `VOID` are terminal. Two counters on the round are recomputed as notes arrive and settle. The round's `unresolved_critical` is true exactly when at least one note in the round has `severity` `CRITICAL` and a status other than `RESOLVED`. Its `open_note_count` counts the round's notes whose status is neither `RESOLVED` nor `VOID`. Adding a note recomputes both counters on the parent round.

Working the notes is the `ConformEditor`'s job. A note may be acknowledged — `OPEN` to `ACKED` — only while its parent round is `OPEN`. Resolution moves a note from `OPEN` or `ACKED` to `RESOLVED`, permitted while the parent round is `OPEN` or `NOTES_CLOSED`, and recomputes the parent round's `unresolved_critical` and `open_note_count`.

Closing a round is a two-step `ReviewerLead` ceremony. Closing the notes moves the round from `OPEN` to `NOTES_CLOSED` and recomputes both counters so the approval decision sees fresh figures. Approval then moves the round from `NOTES_CLOSED` to `APPROVED`, and is permitted only when `unresolved_critical` is false and `open_note_count` is zero — a round with any outstanding note, or any unresolved critical one, cannot be approved. Approving a round whose `target_kind` is `CUT` or `DELIVERABLE` recomputes the project's `conform_ready`. Rejection moves a `NOTES_CLOSED` round to `REJECTED`, and when the round's `target_kind` is `DELIVERABLE` the linked deliverable transitions to `REJECTED` with it. Finally, a round still `OPEN` is voided automatically — moving to `VOID` — when the dailies package it targets is revoked or the turnover it targets is voided; voiding a round voids every note still `OPEN` inside it. Rounds can be listed with `target_kind` and `status` filters, notes with `round_id`, `severity`, and `status` filters, and the round side exposes the reverse listing of its notes.

### 3.7. Deliverable Mastering and Quality Control

The project's contractual output is the **Deliverable**. A `ConformEditor` creates one with a `spec_kind` of `MEZZANINE` or `BROADCAST`, the `sequence_label` being mastered, a `container` of `MXF_OP1A`, `MOV_PRORES`, or `IMF`, and a `requires_qc` flag. The deliverable starts in `SPEC_DRAFT`, and creating a new deliverable with the same `sequence_label` and `spec_kind` supersedes the prior one: a predecessor still in `SPEC_DRAFT` transitions to `SUPERSEDED` at creation, and one already `RENDERING` is transitioned to `SUPERSEDED` by the system when the newer deliverable is created. Two computed fields track progress: `render_progress_pct`, which runs from 0 to 100 and reads exactly 100 whenever the deliverable is in `RENDERED`, `QC_QUEUED`, `QC_PASSED`, `QC_FAILED`, or `DELIVERED`; and `qc_attempt_count`, the number of QC reports recorded against the deliverable.

Rendering is the `ConformEditor`'s launch action and is OCC-guarded per §2.7: the request must carry `expected_project_version` matching the project's current `version`, and a mismatch is rejected with `ERR_STALE_VERSION`. From `SPEC_DRAFT`, rendering is permitted only when the project's `conform_ready` is true — the readiness definition in §3.1 is the gate that keeps render farms from mastering against an unsettled conform. From `QC_FAILED`, re-rendering is permitted only while `qc_attempt_count` is below three attempts; once three attempts are on record the render request is rejected with `ERR_QC_ATTEMPTS_EXHAUSTED`. Either way a successful render moves the deliverable to `RENDERING`, increments the project's `version` by one, and starts `render_progress_pct` reporting from 0. Marking the render complete moves it to `RENDERED` and sets `render_progress_pct` to 100.

Quality control begins when a `QCOperator` enqueues a `RENDERED` deliverable, moving it to `QC_QUEUED`; enqueueing is permitted only when `requires_qc` is true. The verdict arrives as a **QCReport** appended by a `QCOperator` with a `verdict` of `PASS` or `FAIL`, an optional `asset_id` scoping the failure to one asset (null when the failure is deliverable-wide), and a `fail_codes` list that is required when the verdict is `FAIL` and must be empty on `PASS` — a mismatch is a body-shape violation rejected with `ERR_INVALID_REQUEST`. Each appended report receives `attempt_no` equal to the deliverable's current `qc_attempt_count` plus one, records the issuing operator's `X-User-ID` in `issued_by`, and is immutable thereafter. A `PASS` verdict moves the deliverable from `QC_QUEUED` to `QC_PASSED`. A `FAIL` verdict moves it to `QC_FAILED` and, when the report names an `asset_id`, increments that asset's `qc_fail_count` by one. The attempt counter drives the escalation ladder: with fewer than three attempts recorded, a failed deliverable may loop back to `RENDERING`; at three or more, re-rendering is exhausted and the deliverable instead becomes eligible for rejection.

Delivery is a `PostSupervisor` action with two legitimate paths. A deliverable in `QC_PASSED` moves to `DELIVERED` provided the project is `ACTIVE`. A deliverable whose `requires_qc` is false skips QC entirely and moves from `RENDERED` directly to `DELIVERED`. Rejection is the other exit from `QC_FAILED`: a `PostSupervisor` may reject the deliverable only once `qc_attempt_count` has reached at least three attempts — before that, the request is rejected with `ERR_QC_THRESHOLD_NOT_MET` — and the rejection cascades to review, transitioning the review round whose `target_ref_id` names the deliverable to `REJECTED`. `DELIVERED` and `SUPERSEDED` are terminal; `REJECTED` likewise has no outgoing transitions. Deliverables can be listed with `status` and `spec_kind` filters, and QC reports are listable both under their deliverable and under a named asset, each with a `verdict` filter.

### 3.8. Archive, Retention, and Project Wrap-Up

Long-term preservation runs through the **ArchiveJob**. A `MediaManager` creates one with an `lto_generation` of `LTO7`, `LTO8`, or `LTO9`, a `target_scope` of `SOURCES_ONLY`, `SOURCES_AND_PROXIES`, or `FULL_PROJECT`, and a `retention_years` horizon between 1 and 25. The job starts `QUEUED`. Starting it moves it to `WRITING`, permitted only while no other archive job of the same project is in `WRITING` or `VERIFYING` — the facility writes one tape stream per project at a time. Verification moves the job from `WRITING` to `VERIFYING` and computes `bytes_written` as the total bytes sealed across the job's scope. Sealing moves it from `VERIFYING` to `SEALED`: when the job's `target_scope` is `FULL_PROJECT`, the project itself must already be in `WRAPPING` or `CLOSED`, since a full-project seal is meaningless while editorial is still live. A successful seal stamps `sealed_at` from the logical clock and, for every in-scope asset that has not been purged, sets `retained_until` to `sealed_at` plus the job's `retention_years` counted in fixed 365-day years — a three-year retention extends the horizon by exactly 1095 days, with no leap-day adjustment. A tape write error moves a `WRITING` job to `FAILED` automatically; a `QUEUED` job may be cancelled outright, moving to `CANCELLED`; and a `FAILED` job may be retried, returning it to `QUEUED`. `SEALED` and `CANCELLED` are terminal. Archive jobs can be listed with a `status` filter.

With deliverables settled and at least one tape sealed, the project winds down through three `PostSupervisor` transitions, each guarded by the wrappability check of §2.9 and failing with `ERR_PROJECT_NOT_WRAPPABLE` when its preconditions are unmet.

Wrapping moves the project from `ACTIVE` to `WRAPPING`. Three conditions must hold: every deliverable of the project is in `DELIVERED`, `REJECTED`, or `SUPERSEDED`; every review round whose `target_kind` is `CUT`, `VENDOR_RETURN`, or `DELIVERABLE` is in `APPROVED`, `REJECTED`, or `VOID` — rounds targeting dailies may still be `OPEN`, because the wrap cascade voids them; and the project's `open_change_list_count` is zero. The cascade is substantial: every dailies package still `PUBLISHED` transitions to `REVOKED` as the dailies window closes, each revocation voids every `OPEN` review round targeting the package, and each voided round in turn voids its `OPEN` notes.

Closing moves the project from `WRAPPING` to `CLOSED`. At least one archive job of the project must be `SEALED`, and none may remain in `QUEUED`, `WRITING`, or `VERIFYING`. As the doors close, every edit bay still `AVAILABLE` transitions to `MAINTENANCE`.

Archiving moves the project from `CLOSED` to `ARCHIVED`, its terminal state, and requires that every archive job of the project be in `SEALED` or `CANCELLED`. Archival changes nothing about readability: all child lists and records remain readable afterward.

## 4. Endpoint Definitions

Operations that create a new resource — a project, batch, asset, watermark profile, dailies package, edit bay, booking, turnover package, change list, review round, review note, deliverable, QC report, archive job, vendor, or vendor bid — return `201 Created` with the new resource in the response body. Operations that modify or transition an existing resource return `200 OK` with the updated resource. The table below is a summary only; request payloads, response payloads, and side effects are specified by the narratives of §2 and §3, to which the reader must refer for the complete contract of each operation.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/post-production/projects` | Create a Project (starts in `SETUP`) | PostSupervisor |
| GET | `/post-production/projects` | List projects with pagination and filters | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, ReviewerLead, QCOperator, FacilityAdmin |
| GET | `/post-production/projects/{id}` | Get one project | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, ReviewerLead, QCOperator, FacilityAdmin, VendorRep, Artist |
| POST | `/post-production/projects/{id}/activate` | `SETUP` → `ACTIVE` | PostSupervisor |
| POST | `/post-production/projects/{id}/wrap` | `ACTIVE` → `WRAPPING` | PostSupervisor |
| POST | `/post-production/projects/{id}/close` | `WRAPPING` → `CLOSED` | PostSupervisor |
| POST | `/post-production/projects/{id}/archive` | `CLOSED` → `ARCHIVED` | PostSupervisor |
| POST | `/post-production/projects/{id}/batches` | Declare a MediaBatch | MediaManager |
| GET | `/post-production/projects/{id}/batches` | List batches for a project | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator |
| GET | `/post-production/projects/{id}/batches/{batch_id}` | Get one batch | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator |
| POST | `/post-production/projects/{id}/batches/{batch_id}/start-ingest` | `DECLARED` → `INGESTING` | MediaManager |
| POST | `/post-production/projects/{id}/batches/{batch_id}/finish-ingest` | `INGESTING` → `PROXYING` | MediaManager |
| POST | `/post-production/projects/{id}/batches/{batch_id}/purge` | `FAILED` or `READY` → `PURGED` | MediaManager |
| POST | `/post-production/projects/{id}/assets` | Register a MediaAsset into a batch | MediaManager |
| GET | `/post-production/projects/{id}/assets` | List assets for a project | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, QCOperator |
| GET | `/post-production/projects/{id}/assets/{asset_id}` | Get one asset | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, QCOperator |
| POST | `/post-production/projects/{id}/assets/{asset_id}/proxy-complete` | Test-driving hook: mark the proxy `DONE` and set its byte size | MediaManager |
| POST | `/post-production/projects/{id}/assets/{asset_id}/verify` | `INGESTED` → `VERIFIED` | MediaManager |
| POST | `/post-production/projects/{id}/assets/{asset_id}/conform` | `VERIFIED` → `CONFORMED` | ConformEditor |
| POST | `/post-production/projects/{id}/assets/{asset_id}/lock` | `CONFORMED` → `LOCKED` | ConformEditor |
| POST | `/post-production/projects/{id}/watermark-profiles` | Create a WatermarkProfile (`DRAFT`) | PostSupervisor |
| GET | `/post-production/projects/{id}/watermark-profiles` | List watermark profiles | PostSupervisor, DailiesCoordinator |
| POST | `/post-production/projects/{id}/watermark-profiles/{profile_id}/activate` | `DRAFT` → `ACTIVE` | PostSupervisor |
| POST | `/post-production/projects/{id}/watermark-profiles/{profile_id}/retire` | `ACTIVE` → `RETIRED` | PostSupervisor |
| POST | `/post-production/projects/{id}/dailies` | Create a DailiesPackage (`DRAFT`) | DailiesCoordinator |
| GET | `/post-production/projects/{id}/dailies` | List dailies packages | PostSupervisor, DailiesCoordinator, ReviewerLead |
| GET | `/post-production/projects/{id}/dailies/{package_id}` | Get one dailies package | PostSupervisor, DailiesCoordinator, ReviewerLead |
| POST | `/post-production/projects/{id}/dailies/{package_id}/publish` | `DRAFT` → `PUBLISHED` | DailiesCoordinator |
| POST | `/post-production/projects/{id}/dailies/{package_id}/revoke` | `PUBLISHED` → `REVOKED` | DailiesCoordinator |
| POST | `/post-production/projects/{id}/bays` | Register an EditBay | PostSupervisor |
| GET | `/post-production/projects/{id}/bays` | List bays | PostSupervisor, ConformEditor, Artist |
| POST | `/post-production/projects/{id}/bays/{bay_id}/maintenance` | `AVAILABLE` → `MAINTENANCE` | PostSupervisor |
| POST | `/post-production/projects/{id}/bays/{bay_id}/release` | `MAINTENANCE` → `AVAILABLE` | PostSupervisor |
| POST | `/post-production/projects/{id}/bays/{bay_id}/decommission` | `AVAILABLE` or `MAINTENANCE` → `DECOMMISSIONED` | PostSupervisor |
| POST | `/post-production/projects/{id}/bookings` | Create a Booking (`RESERVED`); OCC-guarded on the bay | PostSupervisor, Artist |
| GET | `/post-production/projects/{id}/bookings` | List bookings | PostSupervisor, ConformEditor, Artist |
| GET | `/post-production/projects/{id}/bookings/{booking_id}` | Get one booking | PostSupervisor, ConformEditor, Artist |
| POST | `/post-production/projects/{id}/bookings/{booking_id}/check-in` | `RESERVED` → `CHECKED_IN` | Artist |
| POST | `/post-production/projects/{id}/bookings/{booking_id}/complete` | `CHECKED_IN` → `COMPLETED` | Artist |
| POST | `/post-production/projects/{id}/bookings/{booking_id}/cancel` | `RESERVED` → `CANCELLED` | PostSupervisor, Artist |
| POST | `/post-production/projects/{id}/turnovers` | Create a TurnoverPackage (`DRAFT`) | ConformEditor |
| GET | `/post-production/projects/{id}/turnovers` | List turnovers | PostSupervisor, ConformEditor, VendorRep, ReviewerLead |
| GET | `/post-production/projects/{id}/turnovers/{turnover_id}` | Get one turnover | PostSupervisor, ConformEditor, VendorRep, ReviewerLead |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/stage` | `DRAFT` → `STAGED` | ConformEditor |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/issue` | `STAGED` → `ISSUED` | PostSupervisor |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/ack` | `ISSUED` → `ACKED` | VendorRep |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/return` | `ACKED` → `RETURNED`; auto-creates a review round | VendorRep |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/close` | `RETURNED` → `CLOSED` | PostSupervisor |
| POST | `/post-production/projects/{id}/turnovers/{turnover_id}/void` | `DRAFT` → `VOID` | PostSupervisor |
| POST | `/post-production/projects/{id}/change-lists` | Create a ChangeList against a turnover | ConformEditor |
| GET | `/post-production/projects/{id}/change-lists` | List change lists | PostSupervisor, ConformEditor, VendorRep |
| POST | `/post-production/projects/{id}/change-lists/{change_list_id}/apply` | `OPEN` → `APPLIED`; OCC-guarded on the turnover | ConformEditor |
| POST | `/post-production/projects/{id}/change-lists/{change_list_id}/reject` | `OPEN` → `REJECTED` | ConformEditor |
| POST | `/post-production/projects/{id}/review-rounds` | Open a ReviewRound against an existing target | ReviewerLead |
| GET | `/post-production/projects/{id}/review-rounds` | List review rounds | PostSupervisor, ReviewerLead, ConformEditor, DailiesCoordinator |
| GET | `/post-production/projects/{id}/review-rounds/{round_id}` | Get one review round | PostSupervisor, ReviewerLead, ConformEditor |
| POST | `/post-production/projects/{id}/review-rounds/{round_id}/close-notes` | `OPEN` → `NOTES_CLOSED` | ReviewerLead |
| POST | `/post-production/projects/{id}/review-rounds/{round_id}/approve` | `NOTES_CLOSED` → `APPROVED` | ReviewerLead |
| POST | `/post-production/projects/{id}/review-rounds/{round_id}/reject` | `NOTES_CLOSED` → `REJECTED` | ReviewerLead |
| POST | `/post-production/projects/{id}/review-notes` | Add a ReviewNote to a round | ReviewerLead, ConformEditor, PostSupervisor |
| GET | `/post-production/projects/{id}/review-notes` | List review notes | PostSupervisor, ReviewerLead, ConformEditor |
| POST | `/post-production/projects/{id}/review-notes/{note_id}/ack` | `OPEN` → `ACKED` | ConformEditor |
| POST | `/post-production/projects/{id}/review-notes/{note_id}/resolve` | `OPEN` or `ACKED` → `RESOLVED` | ConformEditor |
| POST | `/post-production/projects/{id}/deliverables` | Create a Deliverable (`SPEC_DRAFT`); supersedes the prior non-terminal deliverable with the same sequence and spec | ConformEditor |
| GET | `/post-production/projects/{id}/deliverables` | List deliverables | PostSupervisor, ConformEditor, QCOperator |
| GET | `/post-production/projects/{id}/deliverables/{deliverable_id}` | Get one deliverable | PostSupervisor, ConformEditor, QCOperator |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/render` | `SPEC_DRAFT` or `QC_FAILED` → `RENDERING`; OCC-guarded on the project | ConformEditor |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/render-complete` | `RENDERING` → `RENDERED` | ConformEditor |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/enqueue-qc` | `RENDERED` → `QC_QUEUED` | QCOperator |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/qc-reports` | Append a QCReport; `PASS` → `QC_PASSED`, `FAIL` → `QC_FAILED` | QCOperator |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/deliver` | `QC_PASSED` → `DELIVERED`, or `RENDERED` → `DELIVERED` when QC is not required | PostSupervisor |
| POST | `/post-production/projects/{id}/deliverables/{deliverable_id}/reject` | `QC_FAILED` → `REJECTED` after the attempt threshold | PostSupervisor |
| GET | `/post-production/projects/{id}/deliverables/{deliverable_id}/qc-reports` | List QC reports for a deliverable | PostSupervisor, ConformEditor, QCOperator |
| POST | `/post-production/projects/{id}/archive-jobs` | Create an ArchiveJob (`QUEUED`) | MediaManager |
| GET | `/post-production/projects/{id}/archive-jobs` | List archive jobs | PostSupervisor, MediaManager |
| GET | `/post-production/projects/{id}/archive-jobs/{job_id}` | Get one archive job | PostSupervisor, MediaManager |
| POST | `/post-production/projects/{id}/archive-jobs/{job_id}/start` | `QUEUED` → `WRITING` | MediaManager |
| POST | `/post-production/projects/{id}/archive-jobs/{job_id}/verify` | `WRITING` → `VERIFYING` | MediaManager |
| POST | `/post-production/projects/{id}/archive-jobs/{job_id}/seal` | `VERIFYING` → `SEALED` | MediaManager |
| POST | `/post-production/projects/{id}/archive-jobs/{job_id}/cancel` | `QUEUED` → `CANCELLED` | MediaManager |
| POST | `/post-production/projects/{id}/archive-jobs/{job_id}/retry` | `FAILED` → `QUEUED` | MediaManager |
| POST | `/post-production/vendors` | Onboard a vendor | FacilityAdmin |
| GET | `/post-production/vendors` | List vendors | FacilityAdmin, PostSupervisor, VendorRep |
| GET | `/post-production/vendors/{vendor_id}` | Get one vendor | FacilityAdmin, PostSupervisor, VendorRep |
| POST | `/post-production/vendors/{vendor_id}/suspend` | `ONBOARDED` → `SUSPENDED` | FacilityAdmin |
| POST | `/post-production/vendors/{vendor_id}/reinstate` | `SUSPENDED` → `ONBOARDED` | FacilityAdmin |
| POST | `/post-production/vendors/{vendor_id}/offboard` | `SUSPENDED` → `OFFBOARDED` | FacilityAdmin |
| POST | `/post-production/projects/{id}/vendor-bids` | Submit a bid against a `STAGED` turnover | VendorRep |
| GET | `/post-production/projects/{id}/vendor-bids` | List bids | PostSupervisor, VendorRep, FacilityAdmin |
| POST | `/post-production/projects/{id}/vendor-bids/{bid_id}/award` | `SUBMITTED` → `AWARDED` | PostSupervisor |
| POST | `/post-production/projects/{id}/vendor-bids/{bid_id}/withdraw` | `SUBMITTED` → `WITHDRAWN` | VendorRep |
| GET | `/post-production/projects/{id}/bays/{bay_id}/utilization` | Computed read: per-date booking utilization for a bay | PostSupervisor, ConformEditor |
| GET | `/post-production/vendors/{vendor_id}/load` | Computed read: vendor concurrent turnover load | FacilityAdmin, PostSupervisor, VendorRep |
| GET | `/post-production/batches/{id}` | Get one MediaBatch by id (flat alias) | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator |
| GET | `/post-production/batches/{id}/assets` | Reverse reachability: list MediaAssets whose `batch_id` is this batch | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, QCOperator |
| GET | `/post-production/batches/{id}/dailies` | Reverse reachability: list DailiesPackages whose `batch_id` is this batch | PostSupervisor, DailiesCoordinator, ReviewerLead |
| GET | `/post-production/assets/{id}` | Get one MediaAsset by id (flat alias) | PostSupervisor, MediaManager, ConformEditor, DailiesCoordinator, QCOperator |
| GET | `/post-production/assets/{id}/qc-reports` | Reverse reachability: list QCReports whose `asset_id` is this asset | PostSupervisor, ConformEditor, QCOperator |
| GET | `/post-production/watermark-profiles/{id}` | Get one WatermarkProfile by id (flat alias) | PostSupervisor, DailiesCoordinator |
| GET | `/post-production/watermark-profiles/{id}/dailies` | Reverse reachability: list DailiesPackages whose `watermark_profile_id` is this profile | PostSupervisor, DailiesCoordinator, ReviewerLead |
| GET | `/post-production/bays/{id}` | Get one EditBay by id (flat alias) | PostSupervisor, ConformEditor, Artist |
| GET | `/post-production/bays/{id}/bookings` | Reverse reachability: list Bookings whose `bay_id` is this bay | PostSupervisor, ConformEditor, Artist |
| GET | `/post-production/bookings/{id}` | Get one Booking by id (flat alias) | PostSupervisor, ConformEditor, Artist |
| GET | `/post-production/turnovers/{id}` | Get one TurnoverPackage by id (flat alias) | PostSupervisor, ConformEditor, VendorRep, ReviewerLead |
| GET | `/post-production/turnovers/{id}/change-lists` | Reverse reachability: list ChangeLists whose `turnover_id` is this turnover | PostSupervisor, ConformEditor, VendorRep |
| GET | `/post-production/turnovers/{id}/vendor-bids` | Reverse reachability: list VendorBids whose `turnover_id` is this turnover | PostSupervisor, VendorRep, FacilityAdmin |
| GET | `/post-production/change-lists/{id}` | Get one ChangeList by id (flat alias) | PostSupervisor, ConformEditor, VendorRep |
| GET | `/post-production/review-rounds/{id}` | Get one ReviewRound by id (flat alias) | PostSupervisor, ReviewerLead, ConformEditor |
| GET | `/post-production/review-rounds/{id}/notes` | Reverse reachability: list ReviewNotes whose `round_id` is this round | PostSupervisor, ReviewerLead, ConformEditor |
| GET | `/post-production/review-notes/{id}` | Get one ReviewNote by id (flat alias) | PostSupervisor, ReviewerLead, ConformEditor |
| GET | `/post-production/deliverables/{id}` | Get one Deliverable by id (flat alias) | PostSupervisor, ConformEditor, QCOperator |
| GET | `/post-production/deliverables/{id}/qc-reports` | Reverse reachability: list QCReports whose `deliverable_id` is this deliverable | PostSupervisor, ConformEditor, QCOperator |
| GET | `/post-production/qc-reports/{id}` | Get one QCReport by id (flat alias) | PostSupervisor, ConformEditor, QCOperator |
| GET | `/post-production/archive-jobs/{id}` | Get one ArchiveJob by id (flat alias) | PostSupervisor, MediaManager |
| GET | `/post-production/vendors/{id}/turnovers` | Reverse reachability: list TurnoverPackages whose `vendor_id` is this vendor | FacilityAdmin, PostSupervisor, VendorRep |
| GET | `/post-production/vendors/{id}/bids` | Reverse reachability: list VendorBids whose `vendor_id` is this vendor | FacilityAdmin, PostSupervisor, VendorRep |
| GET | `/post-production/vendor-bids/{id}` | Get one VendorBid by id (flat alias) | PostSupervisor, VendorRep, FacilityAdmin |
| POST | `/_clock/set_current_utc` | Test-driving capability: set the server's logical clock | FacilityAdmin |

## 5. Error Code Catalogue

The catalogue below enumerates every error identifier and its HTTP status. The conditions that trigger each error are specified in the narratives of §2 and §3 rather than in this table.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_STALE_VERSION` | 412 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_WINDOW_CLOSED` | 422 |
| `ERR_BOOKING_OVERLAP` | 409 |
| `ERR_WATERMARK_NONCOMPLIANT` | 422 |
| `ERR_DISTRIBUTION_INVALID` | 422 |
| `ERR_DUPLICATE_ASSET` | 409 |
| `ERR_VENDOR_INELIGIBLE` | 422 |
| `ERR_VENDOR_CAPACITY_EXCEEDED` | 422 |
| `ERR_STORAGE_QUOTA_EXCEEDED` | 422 |
| `ERR_QC_THRESHOLD_NOT_MET` | 422 |
| `ERR_QC_ATTEMPTS_EXHAUSTED` | 422 |
| `ERR_ASSET_NOT_CONFORMABLE` | 422 |
| `ERR_ARTIST_MISMATCH` | 403 |
| `ERR_BAY_OCCUPIED` | 409 |
| `ERR_PROJECT_NOT_WRAPPABLE` | 422 |
| `ERR_ALREADY_TERMINAL` | 409 |
