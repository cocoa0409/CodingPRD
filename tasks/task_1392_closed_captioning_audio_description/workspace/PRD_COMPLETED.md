# Closed Captioning & Audio Description API — Product Requirements Document

## 1. Introduction

Broadcasters, streaming platforms, and institutional content owners face mounting regulatory and contractual pressure to make programming accessible. FCC broadcast rules, Section 508 procurement requirements, and internal accessibility policies each impose their own accuracy bar on captions, while audio description has become a standard deliverable for streaming catalogs. The operational reality behind those deliverables is unforgiving: source media arrives in half a dozen frame rates, turnaround commitments range from a leisurely standard queue to same-day air deadlines, accuracy must be measured and defended with weighted error scoring, live events need certified stenographers booked against hard daily capacity caps, and every finished asset must be archived under a retention class that matches the client's regulatory regime.

This document specifies the Closed Captioning & Audio Description Services API, mounted under `/caption-ad`. It covers the full production lifecycle: media intake and technical inspection, tiered quoting and turnaround commitment, caption authoring with a cyclic QC rework loop, audio description scripting against measured program gaps, live event scheduling with stenographer offer cascades and preemption handling, format conversion and embedding, client error complaints with remediation versioning, and long-term archive retention with legal holds. Every workflow is designed for segregation of duties — the person who authors an artifact is never the person who approves it, and the person who resolves a complaint is never the person whose work was disputed.

All state in the system is manipulated through the REST endpoints catalogued in §4. Time itself is a controllable input: a logical clock governs every temporal rule in this document, and operations staff may advance it through a dedicated capability described in §2.8.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying a role name outside the declared set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). A request whose role is not on the endpoint's authorized list is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

Eight roles are recognized, spelled exactly as follows: `ClientContact`, `IntakeCoordinator`, `CaptionEditor`, `ADProducer`, `QCSpecialist`, `Scheduler`, `Stenographer`, `OperationsManager`.

Two roles are entity-backed. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's `client_id` field to `X-User-ID`. When `X-User-Role` is `Stenographer`, `X-User-ID` is the `id` of the acting `Stenographer`; ownership checks on a `LiveAssignment` compare the assignment's `stenographer_id` to `X-User-ID`. For the remaining roles — `IntakeCoordinator`, `CaptionEditor`, `ADProducer`, `QCSpecialist`, `Scheduler`, and `OperationsManager` — `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `author_user_id` on a caption or audio description track, or as `resolver_user_id` on a complaint) but does not compare it to any entity's `id`.

A `ClientContact` confirms quotes, accepts deliveries, and files or reopens complaints on behalf of their own organization only. An `IntakeCoordinator` registers and inspects media, drafts and quotes work orders, and may cancel orders. A `CaptionEditor` authors caption tracks and drives them from draft through conform, and may also queue conversion jobs. An `ADProducer` writes and produces audio description, including studio bookings. A `QCSpecialist` finalizes accuracy reviews and approves or rejects AD scripts and mixes, and must never be the author of the artifact under review. A `Scheduler` owns the live side of the house: events, the stenographer roster, offers, preemption, no-show marking, and air control. An `OperationsManager` holds the operations authority: client administration, delivery, complaint triage and remediation, conversion execution, archive management, and the clock and sweep capabilities. All roles may read any resource through the list and get endpoints.

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, read from the logical clock of §2.7.
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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100. The `offset` defaults to 0 and may not be negative. A `limit` or `offset` that is not an integer, or that violates these bounds, is rejected with `ERR_VALIDATION` (HTTP 400). Every list response orders its items by `created_at` ascending — ties broken by creation order — and its `meta` object carries the pagination fields `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Resource Identity and Mutation Semantics

Every persisted resource carries an `id` that is a server-minted UUID with no type prefix, and a `created_at` timestamp in ISO 8601 UTC with three fractional digits. All entities except one additionally carry `updated_at`, refreshed to the current instant on every mutation, and `version`, an integer that starts at one on creation and increments by one on every mutation of that entity. The single exception is `QCReview`: a finalized review is an immutable measurement record and carries only `id` and `created_at` — both `updated_at` and `version` are absent from it.

Mutations that create a new resource answer 201; mutations that change an existing resource answer 200. Requests are validated in a fixed order, and the first failing check determines the rejection: authentication of the two headers comes first, then role authorization, then resolution of path identifiers and body foreign keys from left to right (a dangling reference yields `ERR_NOT_FOUND`), then entity-backed ownership (`ERR_FORBIDDEN_OWNERSHIP`), then request shape and field constraints (`ERR_VALIDATION`), then optimistic concurrency, then state-machine admissibility (`ERR_INVALID_TRANSITION`), then segregation-of-duties and compliance rules, then temporal windows, then capacity and geometry constraints, and finally linked-entity state preconditions.

### 2.5. Optimistic Concurrency Control

Three write operations are protected by optimistic concurrency control, each keyed to a parent entity's `version`.

Creating a new caption track version requires the request to carry `expected_work_order_version` equal to the target work order's current `version`. If another writer has advanced the work order's version since the client last read it, the create is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), preventing a stale client from silently superseding a track version it never observed. Amending a work order's `turnaround_tier` or `language` likewise requires `expected_work_order_version` to match the order's current `version`; a mismatch is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), because amendments re-quote and move the expiry window and must not be layered onto an unobserved state. Creating a live assignment offer requires `expected_live_event_version` to match the event's current `version`; a mismatch is rejected with `ERR_STALE_LIVE_EVENT_VERSION` (HTTP 412). Endpoints not named here do not take a version field.

### 2.6. Precision and Rounding

Monetary amounts are integer cents. Accuracy percentages and gap coverage percentages are computed in exact decimal arithmetic — never binary floating point — and rounded half-up: accuracy to two decimal places in a single final rounding step, gap coverage to one decimal place per gap and then one decimal place on the mean. Timestamps used in SLA and window computations are compared at one-second precision with no rounding. Capacity minutes are whole integers.

### 2.7. The Logical Clock and the Operations Sweep

Every temporal rule in this document — quote expiry, offer expiry, check-in windows, SLA breach, escalation aging, certification lapse, retention eligibility — is evaluated against a logical clock, not the host's wall clock. At startup, before any adjustment, the logical clock reads exactly 2026-08-01T00:00:00Z. An `OperationsManager` may advance it through an admin-only test-driving capability that sets the current UTC instant to a supplied `to_iso8601` value; the clock never falls back to wall-clock time afterward.

The clock capability's response body carries a single `current_utc` field echoing the logical instant now in force.

A companion ops-run checkpoint capability applies every standing time-based rule in one pass and returns counts of what it changed: offers past their expiry move `OFFERED` → `OFFER_EXPIRED`; quotes past their expiry move `QUOTED` → `QUOTE_EXPIRED`; work orders whose `due_at` has passed while the order sits `CONFIRMED`, `IN_PRODUCTION`, or `READY_FOR_DELIVERY` are marked with `sla_breached` set true; complaints age and escalate per §3.8; `ACTIVE` stenographers whose `cert_valid_until` has passed move to `CERTIFICATION_LAPSED`; and delivered tracks of client-accepted orders whose work order's `delivered_at` is at least thirty days in the past move to `ARCHIVED`. The checkpoint's response reports `expired_offer_count`, `expired_quote_count`, `sla_breach_count`, `escalated_complaint_count`, `lapsed_certification_count`, and `archived_track_count`.

### 2.8. Turnaround Tiers and Compliance Standards

Four turnaround tiers exist — `STANDARD`, `EXPRESS`, `RUSH`, and `SAME_DAY` — and every client declares a `compliance_standard` of `FCC_BROADCAST`, `SECTION_508`, or `INTERNAL`. The compliance standard drives both the caption accuracy pass threshold (§3.4) and the retention class applied when a delivered track enters the archive (§3.9). The `SAME_DAY` tier is reserved for short programs: a work order naming `SAME_DAY` for media longer than sixty minutes is rejected at creation, and again at amendment, with `ERR_TIER_DURATION_INCOMPATIBLE` (HTTP 422).

### 2.9. Segregation of Duties

Three independence rules are enforced everywhere they apply. The user finalizing a QC review must differ from the track's `author_user_id`; the user approving an AD script or mix must differ from the AD track's `author_user_id`; and the user resolving a complaint must differ from the disputed track's `author_user_id`. Each violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). Separately, `SAMPLED_REVIEW` is never permitted when the owning client's compliance standard is `FCC_BROADCAST`; attempting it is rejected with `ERR_REVIEW_MODE_NOT_PERMITTED` (HTTP 422).

## 3. Business Logic & Workflows

### 3.1. Client Administration and Media Intake

An `OperationsManager` onboards a client by supplying the organization's `name`, its `compliance_standard` (`FCC_BROADCAST`, `SECTION_508`, or `INTERNAL`), and optionally a `default_turnaround_tier` of `STANDARD`, `EXPRESS`, `RUSH`, or `SAME_DAY` that serves as an informational default for new orders — when omitted it defaults to `STANDARD`. A new client starts with `client_status` `ACTIVE` and `ytd_completed_minutes` zero. The status vocabulary is `ACTIVE`, `SUSPENDED`, and `TERMINATED`. Suspending a client moves it `ACTIVE` → `SUSPENDED`; reactivation returns it to `ACTIVE`. A client that is not `ACTIVE` cannot confirm quotes and cannot have live events scheduled — both attempts are rejected with `ERR_CLIENT_NOT_ACTIVE` (HTTP 409).

Media arrives through an `IntakeCoordinator`, who registers each asset with its owning `client_id`, the program `title`, a `media_kind` of `FILE_BASED` or `LIVE_RECORDING`, the `duration_seconds` runtime (which must be greater than zero), and the `frame_rate` — one of `FPS_23_976`, `FPS_24`, `FPS_25`, `FPS_29_97_DF`, `FPS_29_97_NDF`, or `FPS_30`, where `DF` denotes drop-frame. Registration lands the asset in `RECEIVED`. Beginning inspection moves `RECEIVED` → `INSPECTING`. From `INSPECTING` the coordinator either clears the asset (`INSPECTING` → `CLEARED`) or rejects it (`INSPECTING` → `REJECTED_INTAKE`); rejection requires a non-empty `rejection_reason`, which is otherwise null. `REJECTED_INTAKE` is terminal, and a work order referencing such an asset can never be quoted — the quote attempt is rejected with `ERR_INVALID_TRANSITION` (HTTP 409).

### 3.2. Work Orders: Quoting, Confirmation, and the SLA Clock

A work order binds a `client_id`, a `media_asset_id`, a `service_type` of `CAPTIONS`, `AUDIO_DESCRIPTION`, or `BUNDLE`, a `turnaround_tier`, and a BCP-47 `language` such as en-US — accepted as any non-empty string without format validation; the media asset need not belong to the named client, as no cross-ownership check is made at creation. New orders land in `DRAFT`. The full status vocabulary is `DRAFT`, `QUOTED`, `QUOTE_EXPIRED`, `CONFIRMED`, `IN_PRODUCTION`, `READY_FOR_DELIVERY`, `DELIVERED`, `REMEDIATION`, `CLIENT_ACCEPTED`, and `CANCELLED`, with `CLIENT_ACCEPTED` and `CANCELLED` terminal.

Quoting is performed by an `IntakeCoordinator` and moves `DRAFT` → `QUOTED` or, for an expired quote, `QUOTE_EXPIRED` → `QUOTED` — re-quoting is always permitted. The quote computes `quoted_price_cents` and sets `quote_expires_at` to seventy-two hours after the quote instant. The price is built in a pinned evaluation order that must not be rearranged. First, the program length in minutes is the `duration_seconds` divided by sixty and rounded up to a whole minute. Second, a duration charge accumulates across three marginal brackets: the first thirty minutes at 350 cents each, the next sixty minutes at 300 cents each, and every minute beyond ninety at 250 cents each. Third, the tier multiplier is applied to that charge — 1.00 for `STANDARD`, 1.50 for `EXPRESS`, 2.00 for `RUSH`, 2.50 for `SAME_DAY` — and the product is rounded half-up to a whole cent. Fourth, a volume discount is read from the owning client's `ytd_completed_minutes` **as it stands at quote time**: at least 10000 minutes earns ten percent off, at least 5000 earns five percent, otherwise none; the discounted amount is again rounded half-up to a whole cent. Fifth, `quoted_price_cents` is the sum of a 15000-cent setup fee, the discounted amount, and a language fee of 5000 cents for any `language` other than en-US (zero for en-US). Applying the multiplier before the discount is mandatory; reversing those two steps changes the cents whenever the tiered amount times the discount percentage is non-integral.

Confirmation is the client's act: a `ClientContact` whose `X-User-ID` equals the order's `client_id` confirms a `QUOTED` order, provided the client is `ACTIVE` (else `ERR_CLIENT_NOT_ACTIVE`), the confirm instant precedes `quote_expires_at` (at or after expiry the attempt is rejected with `ERR_QUOTE_EXPIRED`, HTTP 409), and the referenced media asset is `CLEARED` (else `ERR_MEDIA_NOT_CLEARED`, HTTP 409); these checks fire in a fixed order — from-state admissibility, then quote expiry, then client-active, then media-cleared. Confirmation runs the turnaround-window calculation and stamps `due_at`.

The SLA window depends on tier and program length. Let the program length in whole minutes, rounded up, be the basis. For `STANDARD`, the allowance is 120 hours covering the first sixty minutes, plus 24 additional hours for each further started hour of program. For `EXPRESS`, it is 48 hours covering the first sixty minutes, plus 12 hours per further started hour. For `RUSH`, it is 24 hours covering the first thirty minutes, plus 6 hours for each further started thirty-minute block. For `SAME_DAY`, it is a flat 8 hours. The clock basis differs by tier: `STANDARD` and `EXPRESS` consume hours only inside business windows — Monday through Friday, 09:00 up to 17:00 UTC, eight hours per day, weekends skipped — and if confirmation lands outside a window, the clock starts at the next window open. `RUSH` and `SAME_DAY` consume wall-clock hours continuously, weekends included. `due_at` is the confirm instant plus the allowance under the tier's clock basis. An identical confirm instant and program length therefore yields a later `due_at` under the business-hours tiers than a naive wall-clock reading whenever a weekend or overnight intervenes.

While a quote sits unconfirmed, the sweep may move it `QUOTED` → `QUOTE_EXPIRED` once the current instant reaches `quote_expires_at`. An `IntakeCoordinator` may also amend a `DRAFT` or `QUOTED` order's `turnaround_tier` or `language` under the OCC rule of §2.5; amendment increments the order's `version`, and when the order is `QUOTED` the quote is recomputed and `quote_expires_at` resets to seventy-two hours from the amendment. Either an `IntakeCoordinator` or an `OperationsManager` may cancel an order from `DRAFT`, `QUOTED`, or `CONFIRMED`.

Production begins when a `CaptionEditor` starts production, moving `CONFIRMED` → `IN_PRODUCTION`. The order then advances `IN_PRODUCTION` → `READY_FOR_DELIVERY` automatically when its required coverage is complete: for `CAPTIONS`, a current caption track (one not in `SUPERSEDED`, `ARCHIVED`, or `QC_FAILED_PERMANENT`) exists and is `CONFORMED`; for `AUDIO_DESCRIPTION`, an AD track is `CONFORMED`; for `BUNDLE`, both conditions hold. Delivery is an `OperationsManager` act that moves `READY_FOR_DELIVERY` → `DELIVERED` and fans out several effects at once: `delivered_at` is stamped and `sla_breached` is set to true exactly when `delivered_at` falls after `due_at`; every `CONFORMED` caption track of the order moves `CONFORMED` → `DELIVERED`, and every `CONFORMED` AD track likewise moves `CONFORMED` → `DELIVERED`; one `ArchiveItem` in `ACTIVE_HOLD` is created per delivered track with its `retention_class` derived from the client's compliance standard; and the client's `ytd_completed_minutes` grows by the program's `duration_seconds` divided by sixty and rounded up to a whole minute. After delivery, the client accepts by moving `DELIVERED` → `CLIENT_ACCEPTED`, which requires the order's `active_complaint_count` to be zero — otherwise the acceptance is rejected with `ERR_COMPLAINTS_STILL_OPEN` (HTTP 409); that complaint-count check fires before the from-state check, so an order already pushed to `REMEDIATION` by an open complaint still rejects acceptance with `ERR_COMPLAINTS_STILL_OPEN`. A later complaint, or a reopen, pushes the order `DELIVERED` → `REMEDIATION` and raises `active_complaint_count` by one; filing a complaint also cancels every `QUEUED` conversion job referencing any track of the order, freezing in-flight conversion work, while a reopen does not re-run that cancellation. Each delivery applies the full fan-out, so a re-delivery after remediation grows `ytd_completed_minutes` by the program length again. When remediation begins the order returns `REMEDIATION` → `IN_PRODUCTION`; when instead a complaint is dismissed before any remediation and the count falls back to zero, the order returns `REMEDIATION` → `DELIVERED`.

### 3.3. Caption Track Authoring and Versioning

Caption tracks are created by a `CaptionEditor` against an order that is `IN_PRODUCTION`, in a payload containing the BCP-47 `language` (accepted as any non-empty string), a `caption_format` of `SCC`, `WEBVTT`, `TTML`, or `SRT`, a `speaker_id_style` of `CHEVRON`, `DASH`, or `NAME_TAG`, the OCC field `expected_work_order_version`, and optionally a `supersedes_track_id` naming the prior version this track replaces (null for a work order's first version), recorded as supplied and not resolved as a foreign key — a dangling value does not yield `ERR_NOT_FOUND`. Creation stamps `author_user_id` with the acting editor's `X-User-ID`, increments the work order's `version` by one, moves any prior current track to `SUPERSEDED`, and assigns the new track a `version_no` one greater than the prior current version (or one for the first). A new track begins in `AUTHORING` with `qc_attempts` zero and `last_accuracy_pct` null. Its full status vocabulary is `AUTHORING`, `INTERNAL_REVIEW`, `QC_QUEUED`, `QC_PASSED`, `QC_FAILED`, `QC_FAILED_PERMANENT`, `CONFORMED`, `DELIVERED`, `DISPUTED`, `SUPERSEDED`, and `ARCHIVED`, with `SUPERSEDED`, `ARCHIVED`, and `QC_FAILED_PERMANENT` terminal.

The authoring loop is cyclic. Submitting moves `AUTHORING` → `INTERNAL_REVIEW`; the editor may then return it `INTERNAL_REVIEW` → `AUTHORING` or enqueue it `INTERNAL_REVIEW` → `QC_QUEUED`. A finalized QC review (§3.4) drives the outcome: a `PASS` moves `QC_QUEUED` → `QC_PASSED` and records the review's accuracy in `last_accuracy_pct`; a `FAIL` moves `QC_QUEUED` → `QC_FAILED`, increments `qc_attempts` by one, records `last_accuracy_pct` the same way, and — the moment `qc_attempts` reaches three — immediately moves the track on to `QC_FAILED_PERMANENT`. Rework moves `QC_FAILED` → `AUTHORING`, but only while `qc_attempts` is below three; once the third failure lands the track is already `QC_FAILED_PERMANENT` and terminal, so a rework attempt there is rejected as an invalid transition with `ERR_INVALID_TRANSITION` (HTTP 409). A permanently failed track blocks the order: the work order remains `IN_PRODUCTION` yet cannot reach `READY_FOR_DELIVERY` until a fresh version is created and conformed.

Marking a `QC_PASSED` track conformed moves `QC_PASSED` → `CONFORMED`, requires the work order to be `IN_PRODUCTION` (any other posture is rejected with `ERR_INVALID_TRANSITION`), and triggers the work order's coverage recompute described in §3.2 — when the required coverage is complete the order bubbles up to `READY_FOR_DELIVERY`. Delivery of the order carries each `CONFORMED` track to `DELIVERED`. A complaint against a delivered track moves it `DELIVERED` → `DISPUTED` and freezes its archive item; dismissal of the complaint returns `DISPUTED` → `DELIVERED` and lifts the freeze, while beginning remediation on a caption complaint moves `DISPUTED` → `SUPERSEDED`. Independently, whenever a new caption track version is created for the same work order — directly or through remediation — any existing track in `AUTHORING`, `INTERNAL_REVIEW`, `QC_QUEUED`, `QC_PASSED`, or `QC_FAILED` moves to `SUPERSEDED`. Finally, the sweep moves a `DELIVERED` track to `ARCHIVED` once its work order is `CLIENT_ACCEPTED` and the work order's `delivered_at` lies at least thirty days in the past.

### 3.4. Accuracy QC and Compliance Thresholds

A `QCSpecialist` finalizes an accuracy review on a `QC_QUEUED` track by supplying a `review_mode` of `FULL_REVIEW` or `SAMPLED_REVIEW`, the track's `total_words` (greater than zero), and the error counts `minor_errors`, `major_errors`, and `critical_errors` (each zero or more). `sampled_words` is required when the mode is `SAMPLED_REVIEW` and must be at least the value of `total_words` multiplied by 0.20 and rounded up; it is the denominator for sampled accuracy. Under `FULL_REVIEW`, `sampled_words` may be omitted or null; if supplied it must be an integer, is stored on the review, and plays no role in scoring. The reviewer's `X-User-ID` is recorded as `reviewer_user_id` and must differ from the track's `author_user_id` under §2.9. For an `FCC_BROADCAST` client only `FULL_REVIEW` is permitted — a sampled review there is rejected with `ERR_REVIEW_MODE_NOT_PERMITTED`; `SECTION_508` and `INTERNAL` clients may use either mode.

The review's `weighted_errors` is the sum of `minor_errors` counted once each, `major_errors` counted three times each, and `critical_errors` counted ten times each. The accuracy denominator is `total_words` under `FULL_REVIEW` and `sampled_words` under `SAMPLED_REVIEW`; identical error counts and `total_words` therefore yield different accuracies across the two modes whenever the sample is smaller than the whole track. The review's `accuracy_pct` is one minus the weighted errors divided by the denominator, the result multiplied by one hundred, computed in exact decimal arithmetic and rounded half-up to two decimal places in a single final rounding step. The `threshold_pct` comes from the owning client's `compliance_standard`: 99.00 for `FCC_BROADCAST`, 98.50 for `SECTION_508`, 95.00 for `INTERNAL`. The `outcome` is `PASS` when `accuracy_pct` is at least `threshold_pct` — the comparison is inclusive — and `FAIL` otherwise. Because rounding happens once before comparison, a raw value of 98.995 rounds to 99.00 and passes the `FCC_BROADCAST` threshold. Review finalization immediately drives the track's state as described in §3.3, and the review itself is immutable once stored.

### 3.5. Audio Description: Gaps, Scripts, and Studio Time

An `ADProducer` creates an AD track against an order that is `IN_PRODUCTION`, supplying the `language`, the voice talent's `narrator_name`, the program's `gaps`, and the placed `segments`; unlike caption track creation, AD track creation takes no OCC field and does not increment the work order's `version`. The `gaps` array lists the program's silence windows usable for description as start and end millisecond pairs, each window's end strictly after its start, windows non-overlapping and in ascending order. The `segments` array places descriptions into those windows; each entry names a `gap_index`, a `duration_ms` that is greater than zero and no longer than the referenced gap's length, and the `text` to be spoken. Creation lands the track in `SCRIPTING` with `author_user_id` set from the caller, and while in `SCRIPTING` the producer may freely edit `gaps`, `segments`, and `narrator_name` — the edit is partial, leaving omitted or null fields unchanged, and editing a track that is not `SCRIPTING` is rejected with `ERR_INVALID_TRANSITION` (HTTP 409). The track's status vocabulary is `SCRIPTING`, `SCRIPT_REVIEW`, `RECORDING`, `MIX_QC`, `CONFORMED`, `DELIVERED`, `DISPUTED`, and `ARCHIVED`, with `ARCHIVED` terminal.

Submitting the script moves `SCRIPTING` → `SCRIPT_REVIEW`, requires `segments` to be non-empty, and computes `gap_coverage_pct`. Coverage is measured per gap first: for each placed segment, its `duration_ms` is divided by the length of its gap in milliseconds, the quotient multiplied by one hundred, and that per-gap utilization rounded half-up to one decimal place. The track's `gap_coverage_pct` is then the mean of those per-gap utilizations, itself rounded half-up to one decimal place. Submission is rejected with `ERR_GAP_COVERAGE_OUT_OF_BAND` (HTTP 422) unless the coverage lands between 35.0 and 85.0 inclusive. The per-gap-first rounding order is pinned: summing all durations and dividing by summed gap lengths with a single rounding would yield a different value whenever the per-gap roundings do not cancel out, and only the per-gap-first result is authoritative.

Script approval by a `QCSpecialist` — who must not be the track's author — moves `SCRIPT_REVIEW` → `RECORDING`; rejection returns it to `SCRIPTING` with a `rejection_note` that is required and must be a non-empty string. While in `RECORDING` the producer books studio time by naming a `studio_id` and a closed-interval booking from `record_start_at` to `record_end_at` (the end must be after the start). Studio geometry differs from stenographer geometry: bookings on the same `studio_id`, across other AD tracks in `RECORDING` or `MIX_QC` with a booking present, conflict unless at least thirty minutes separate them — back-to-back is permitted only when the candidate's end plus thirty minutes is at or before the existing booking's start, or the candidate's start is at or after the existing booking's end plus thirty minutes; a gap of twenty-nine minutes is a conflict and is rejected with `ERR_STUDIO_TURNOVER_VIOLATION` (HTTP 409). A track re-booking itself never conflicts with its own prior booking.

Submitting the mix moves `RECORDING` → `MIX_QC` and requires a booking to be present — `studio_id`, `record_start_at`, and `record_end_at` all non-null — with the current instant at or after `record_end_at`; a submission without a booking, or before `record_end_at`, is rejected with `ERR_INVALID_TRANSITION` (HTTP 409). Mix approval by a `QCSpecialist` (again not the author) moves `MIX_QC` → `CONFORMED` and triggers the same work-order coverage recompute as caption conform. Mix rejection returns `MIX_QC` → `RECORDING` with a `rejection_note` that is required and must be a non-empty string, and clears the studio booking — `studio_id`, `record_start_at`, and `record_end_at` are wiped, so the producer must book again before the next mix submission. From `CONFORMED`, delivery, dispute, dismissal, and the thirty-day archive sweep behave exactly as they do for caption tracks. One asymmetry matters: AD remediation does not version. Beginning remediation on a disputed AD track moves `DISPUTED` → `SCRIPTING` on the same track, clearing its studio booking and making its `gaps` and `segments` editable again.

### 3.6. Live Events and the Stenographer Roster

A `Scheduler` schedules a live captioned event by supplying the owning `client_id`, a `title`, a logical `channel_id` label (not a foreign key), the air window from `start_at` to `end_at` (end strictly after start), and a `required_certification` of `CERT_CBC` or `CERT_CART`. Optional `prep_minutes` (default 15) and `wrap_minutes` (default 5) define pre-show and post-show buffers used in occupancy windows; both must be zero or more. The client must be `ACTIVE`. A new event lands in `SCHEDULED`; its vocabulary is `SCHEDULED`, `BRIEFED`, `ON_AIR`, `WRAP`, `SETTLED`, and `CANCELLED`, with `SETTLED` and `CANCELLED` terminal.

The roster holds stenographers registered by a `Scheduler` with a `display_name`, a `certification` of `CERT_CBC` or `CERT_CART`, the `certified_since` grant date, and a `cert_valid_until` expiry that must fall after the grant. An optional `max_daily_live_minutes` caps committed minutes per UTC day, defaults to 300, and when supplied must be an integer of at least one. A stenographer begins `ACTIVE`; suspension moves `ACTIVE` → `SUSPENDED` and reinstatement moves `SUSPENDED` → `ACTIVE`; the sweep moves an `ACTIVE` stenographer past `cert_valid_until` to `CERTIFICATION_LAPSED`; and renewal — supplying a new `cert_valid_until` later than the current instant — moves `CERTIFICATION_LAPSED` → `ACTIVE` with the new expiry stored; a new expiry not later than the current instant is rejected with `ERR_INVALID_TRANSITION` (HTTP 409). The roster also accumulates two counters: `make_up_minutes_credited`, the cumulative `booked_minutes` of assignments lost to preemption, and `no_show_count`, the cumulative no-show marks.

### 3.7. Offers, Check-In, Preemption, and Air Control

An assignment offer is created by a `Scheduler` against an event — admitted whatever the event's status — carrying the OCC field `expected_live_event_version` and optionally a `stenographer_id`. Creation increments the event's `version`, stamps `offered_at` with the creation instant, computes `offer_expires_at` as the earlier of four hours after `offered_at` and the event's `start_at`, and computes `booked_minutes` as the event's air time in seconds divided by sixty and rounded up, plus its `prep_minutes` and `wrap_minutes`. The assignment lands in `OFFERED`; its vocabulary is `OFFERED`, `ACCEPTED`, `DECLINED`, `OFFER_EXPIRED`, `CONFIRMED`, `LIVE`, `COMPLETED`, `NO_SHOW`, `PREEMPTED`, and `CANCELLED`, with all but the first three and `CONFIRMED`/`LIVE` terminal.

When `stenographer_id` is supplied the offer is direct and its `origin` is `MANUAL`; the named stenographer must be eligible — `ACTIVE`, certification matching the event's `required_certification`, and `cert_valid_until` no earlier than the event's `end_at` — or the create is rejected with `ERR_NO_ELIGIBLE_STENOGRAPHER` (HTTP 422), and overlap and capacity are checked at create time as described below. When `stenographer_id` is omitted, the auto-offer selector runs and the resulting offer's `origin` is `AUTO_OFFER`.

The selector's candidate pool contains every stenographer satisfying all of the following: `steno_status` `ACTIVE`; `certification` exactly equal to the event's `required_certification`; `cert_valid_until` no earlier than the event's `end_at`; no occupancy conflict with the candidate event under the overlap rule; committed minutes for the event's UTC day plus the event's `booked_minutes` not exceeding `max_daily_live_minutes`; no existing assignment for this event in `OFFERED`, `ACCEPTED`, `CONFIRMED`, or `LIVE`; and no existing assignment for this event in `DECLINED`, `PREEMPTED`, `NO_SHOW`, or `OFFER_EXPIRED` — an exclusion memory ensuring a stenographer who declined or was removed from this event is never re-offered it. Ranking is by committed minutes on the event day ascending, then `certified_since` ascending (seniority wins ties), then `created_at` ascending, with any remaining tie broken by roster creation order; the first candidate by that order wins. An empty pool behaves differently by trigger: a direct create with an omitted `stenographer_id` is rejected with `ERR_NO_ELIGIBLE_STENOGRAPHER`, while a decline or preemption cascade silently creates nothing and leaves the event under-covered.

Acceptance is the stenographer's own act: the caller must be the assignment's `stenographer_id` (else `ERR_FORBIDDEN_OWNERSHIP`), the instant must precede `offer_expires_at` (at or after it, the accept is rejected with `ERR_OFFER_EXPIRED`, HTTP 409), and two safety checks re-run at accept time. First, the overlap rule: an assignment's occupancy window runs from the event's `start_at` minus its `prep_minutes` to the event's `end_at` plus its `wrap_minutes`, half-open, with the buffers asymmetric — prep on the left, wrap on the right. The candidate conflicts with any existing assignment of the same stenographer in `ACCEPTED`, `CONFIRMED`, or `LIVE` whenever the candidate window's start precedes the existing window's end and the candidate window's end follows the existing window's start; touching edges — a candidate starting exactly where another ends — are not a conflict. Two events whose raw air times do not overlap still conflict when their buffers intersect. A conflict is rejected with `ERR_STENOGRAPHER_DOUBLE_BOOKED` (HTTP 409). Second, the capacity rule: the stenographer's committed minutes for the event's UTC day — the sum of `booked_minutes` over that stenographer's assignments in `ACCEPTED`, `CONFIRMED`, or `LIVE` whose events start on that day — plus the candidate's `booked_minutes` must not exceed `max_daily_live_minutes`. Equality is allowed; one minute over is rejected with `ERR_CAPACITY_EXCEEDED` (HTTP 422).

Declining moves `OFFERED` → `DECLINED` — again the caller must own the assignment — and triggers the selector with the decliner excluded, producing one `AUTO_OFFER` to the next-ranked eligible stenographer or, when the pool is empty, nothing at all. The sweep expires unanswered offers, moving `OFFERED` → `OFFER_EXPIRED` once the instant reaches `offer_expires_at`.

Check-in moves `ACCEPTED` → `CONFIRMED`, requires ownership, and is only admitted inside a twenty-minute window: from thirty minutes before the event's `start_at` through ten minutes before it, both bounds inclusive; outside that window the attempt is rejected with `ERR_CHECKIN_WINDOW_CLOSED` (HTTP 409). The event's posture follows its coverage: the first assignment to reach `CONFIRMED` moves the event `SCHEDULED` → `BRIEFED`.

Preemption is the scheduler's override. It moves an `ACCEPTED` or `CONFIRMED` assignment to `PREEMPTED` and requires a `preemption_reason` of `SCHEDULER_OVERRIDE`, `EMERGENCY_REBOOK`, or `CLIENT_REQUEST`. Preemption compensates the displaced stenographer: `make_up_minutes_credited` grows by the assignment's `booked_minutes`, and the committed minutes are released. If no `CONFIRMED` assignments remain and the event was `BRIEFED`, the event falls back to `SCHEDULED`; on every preemption the selector then runs, excluding both the preempted stenographer and every stenographer with a prior `DECLINED`, `PREEMPTED`, or `NO_SHOW` assignment for the event. A no-show, marked by the scheduler at or after the event's `start_at` (a mark attempted before it is rejected with `ERR_INVALID_TRANSITION`, HTTP 409), moves `ACCEPTED` or `CONFIRMED` to `NO_SHOW`: `no_show_count` increments, committed minutes are released without make-up credit, the event falls back `BRIEFED` → `SCHEDULED` when no `CONFIRMED` remain, and — unlike preemption — no auto-offer cascade runs.

Air control belongs to the `Scheduler`. Going on air moves `SCHEDULED` or `BRIEFED` to `ON_AIR`, requires at least one `CONFIRMED` assignment (else `ERR_GO_ON_AIR_BLOCKED`, HTTP 409), and is admitted only from thirty minutes before `start_at` up to (but not including) `end_at` — outside that span the attempt is rejected with `ERR_INVALID_TRANSITION`. Going on air moves every `CONFIRMED` assignment to `LIVE`. Wrapping moves `ON_AIR` → `WRAP`, requires the instant to be at or after `end_at` (a wrap attempted before `end_at` is rejected with `ERR_INVALID_TRANSITION`, HTTP 409), and moves every `LIVE` assignment to `COMPLETED`. Settling moves `WRAP` → `SETTLED` and creates the event's `ArchiveItem` in `ACTIVE_HOLD` with `retention_class` `LIVE_ONLY`. Cancelling — permitted from `SCHEDULED` or `BRIEFED` — moves the event to `CANCELLED` and every assignment in `OFFERED`, `ACCEPTED`, or `CONFIRMED` to `CANCELLED`, with no make-up credit. A conservation invariant ties the counters together: for each stenographer and UTC day, the committed minutes plus the released minutes always equal the total `booked_minutes` of assignments that ever reached `ACCEPTED`.

### 3.8. Error Complaints and Remediation

A `ClientContact` opens a complaint against exactly one subject — a delivered caption track via `caption_track_id`, a delivered AD track via `audio_description_track_id`, or a wrapped or settled live event via `live_event_id`; a body with zero or multiple subjects non-null is rejected with `ERR_VALIDATION` (HTTP 400). The complaint's `client_id` is derived from the subject's owning client — any `client_id` in the request body is ignored — and the caller's `X-User-ID` must equal it; the complaint must be opened within thirty days inclusive of the subject's completion — for tracks, the work order's most recent `delivered_at`; for live events, the event's `end_at` — otherwise the filing is rejected with `ERR_COMPLAINT_WINDOW_CLOSED` (HTTP 409). A subject not in the required state — a track not `DELIVERED`, or an event not `WRAP` or `SETTLED` — is rejected with `ERR_INVALID_TRANSITION` (HTTP 409). A subject with an existing complaint in `OPEN`, `TRIAGED`, `REMEDIATING`, or `REOPENED` rejects a second filing with `ERR_COMPLAINT_ALREADY_OPEN` (HTTP 409). The complaint body carries a `severity` of `FCC_CRITICAL`, `MAJOR`, or `MINOR` and a free-text `description`. A new complaint lands `OPEN` with `escalation_level` zero.

Filing against a track cascades: the subject track moves `DELIVERED` → `DISPUTED`, its archive item (if any) sets `dispute_freeze` true, the owning work order moves `DELIVERED` → `REMEDIATION` with `active_complaint_count` raised by one — the order transition applies only when the order is currently `DELIVERED`, so a `CLIENT_ACCEPTED` order remains `CLIENT_ACCEPTED` while the complaint still counts against it — and any `QUEUED` conversion jobs referencing the order's tracks are cancelled. The order's `active_complaint_count` counts complaints on any of its tracks in `OPEN`, `TRIAGED`, `REMEDIATING`, or `REOPENED`.

Triage by an `OperationsManager` moves `OPEN` or `REOPENED` to `TRIAGED` and may re-grade the `severity` when a new one is supplied. Dismissal — from `OPEN` or `TRIAGED`, with a `rationale` required — moves the complaint to its terminal `DISMISSED` state and unwinds the cascade: the subject track returns `DISPUTED` → `DELIVERED`, the archive item's `dispute_freeze` clears, and `active_complaint_count` drops by one; when it reaches zero the order returns `REMEDIATION` → `DELIVERED`.

Beginning remediation moves `TRIAGED` → `REMEDIATING` and is only defined for track subjects — a live-event subject is rejected with `ERR_INVALID_TRANSITION`, since live events have no remediation artifact. For a caption subject, the system creates a new remediation caption track: its `version_no` is the disputed track's plus one, it inherits the disputed track's `language`, `caption_format`, and `speaker_id_style`, it lands in `AUTHORING`, its `supersedes_track_id` points at the disputed track, its `author_user_id` is the acting user, and the complaint's `remediation_track_id` is set to it while the disputed track moves `DISPUTED` → `SUPERSEDED`. For an AD subject, the disputed track itself reopens `DISPUTED` → `SCRIPTING` with no new version. Either way the work order moves `REMEDIATION` → `IN_PRODUCTION`, and the remediation artifact then flows through the normal pipeline — author, review, QC, conform, redeliver.

Resolution splits by subject. For a caption or AD subject (`REMEDIATING` → `RESOLVED`), the remediation artifact — the `remediation_track_id` track for captions, the reopened AD track itself for audio description — must be `DELIVERED`, else the resolve is rejected with `ERR_RESOLUTION_ARTIFACT_INCOMPLETE` (HTTP 409); and the resolver's `X-User-ID` must differ from the disputed track's `author_user_id` under §2.9. For a live-event subject (`TRIAGED` → `RESOLVED`), no artifact exists and a `resolution_note` is required instead. Resolution stamps `resolved_at` and `resolver_user_id`, clears `dispute_freeze` on the archive item — for a caption subject, on the archive items of both the remediation track and the original disputed track — and — for track subjects — lowers `active_complaint_count` by one; live events have no work order, so their count is unaffected. For track subjects the from-state check, the segregation-of-duties check, and the artifact-`DELIVERED` check fire in that order.

A client may reopen a `RESOLVED` complaint within fourteen days inclusive of `resolved_at`; later attempts are rejected with `ERR_REOPEN_WINDOW_CLOSED` (HTTP 409), and the caller must own the complaint. Reopening moves `RESOLVED` → `REOPENED`, increments `escalation_level` by one, and re-disputes the current artifact — the remediation track when `remediation_track_id` is set, otherwise the original subject track — moving it `DELIVERED` → `DISPUTED` with `dispute_freeze` re-applied, and pushes the work order back `DELIVERED` → `REMEDIATION` with the count raised again; the track and order transitions each apply only when the record currently sits in the named from-state, while `dispute_freeze` is re-applied regardless. From `REOPENED`, triage moves `REOPENED` → `TRIAGED` and restarts the cycle.

Complaints also age under the sweep. For every complaint in `OPEN`, `TRIAGED`, `REMEDIATING`, or `REOPENED` — `RESOLVED` and `DISMISSED` complaints do not escalate — the age in whole hours is measured from the complaint's `updated_at` to the current instant, and when that age reaches the severity's threshold the `escalation_level` increments by one: twenty-four hours for `FCC_CRITICAL`, forty-eight for `MAJOR`, seventy-two for `MINOR`, with the threshold inclusive. Because escalation is itself a mutation, `updated_at` refreshes and the next escalation requires another full threshold period. Reopen adds its own increment immediately, outside the sweep.

### 3.9. Format Conversion and the Archive

A conversion job transcodes a finished caption track into another container or embeds captions into media. Creation — by an `OperationsManager` or a `CaptionEditor` — names a `source_track_id`, a `target_format` of `SCC`, `WEBVTT`, `TTML`, or `SRT`, and optionally an `embed` flag (default false). The source track must be in `CONFORMED`, `DELIVERED`, `SUPERSEDED`, or `ARCHIVED` (else `ERR_SOURCE_TRACK_NOT_FINAL`, HTTP 409); the `target_format` must differ from the source track's `caption_format` (else `ERR_CONVERSION_SAME_FORMAT`, HTTP 422); and `embed` is only supported when the target is `SCC` (else `ERR_EMBED_NOT_SUPPORTED`, HTTP 422) — the same-format and embed checks firing before the source-track state check. A new job lands `QUEUED` with `attempt_count` zero; its vocabulary is `QUEUED`, `CONVERTING`, `VALIDATING`, `COMPLETED`, `FAILED_VALIDATION`, and `CANCELLED`, with `COMPLETED` and `CANCELLED` terminal.

One run executes a full conversion pass as a single atomic call: internally the job passes `QUEUED` → `CONVERTING` → `VALIDATING` without resting in either intermediate state, and the caller supplies the worker-measured `output_duration_ms`, a required integer. The job's `last_delta_ms` is the signed difference between `output_duration_ms` and the source media's `duration_seconds` expressed in milliseconds. When the absolute value of that delta is at most 250 milliseconds the pass ends `VALIDATING` → `COMPLETED`; when it exceeds 250 milliseconds the pass ends `VALIDATING` → `FAILED_VALIDATION`, `attempt_count` increments by one, and both `output_duration_ms` and `last_delta_ms` are stored either way. Externally, one run takes the job from `QUEUED` to either `COMPLETED` or `FAILED_VALIDATION`. A failed job may be requeued — moving `FAILED_VALIDATION` → `QUEUED` — only while `attempt_count` is below three; at three the retry is rejected with `ERR_RETRY_LIMIT_REACHED` (HTTP 409). A `QUEUED` job may be cancelled outright — `QUEUED` → `CANCELLED` — and the system also cancels every `QUEUED` job whose source track belongs to a work order when a complaint filing disputes a track of that order; a reopen that re-disputes a track does not cancel jobs.

The archive holds one item per delivered track per delivery — a track delivered again after remediation receives a fresh item — and one per settled live event. Exactly one of its three subject references — `caption_track_id`, `audio_description_track_id`, `live_event_id` — is non-null. Its `retention_class` is computed at creation: `REGULATED_BROADCAST`, retaining 2555 days, when the owning client is `FCC_BROADCAST`; `LIVE_ONLY`, retaining 90 days, for live-event subjects; and `STANDARD`, retaining 1095 days, otherwise. An item begins in `ACTIVE_HOLD`; its vocabulary is `ACTIVE_HOLD`, `COLD_STORE`, `RESTORE_PENDING`, `RESTORED_HOT`, and `PURGED`, with `PURGED` terminal.

Cold storage moves `ACTIVE_HOLD` → `COLD_STORE`, is blocked while `dispute_freeze` is true (rejected with `ERR_INVALID_TRANSITION`), and pins the retention clock: `archived_at` is stamped with the current instant and `purge_after` is computed once as `archived_at` plus the retention class's days, never recomputed afterward. Restore moves `COLD_STORE` → `RESTORE_PENDING` → `RESTORED_HOT`, and rearchiving returns `RESTORED_HOT` → `COLD_STORE` **without** recomputing `archived_at` or `purge_after` — the retention clock keeps running from the original cold-store instant.

Purge moves `COLD_STORE` → `PURGED` and is gated on three conditions evaluated in prose order: the current instant must be at or past `purge_after` — purging exactly at `purge_after` succeeds, earlier attempts are rejected with `ERR_RETENTION_NOT_ELAPSED` (HTTP 409); `legal_hold` must be false — purging under a legal hold is rejected with `ERR_ARCHIVE_LEGAL_HOLD` (HTTP 409); and both `dispute_freeze` must be false and no complaint on the subject may exist in `OPEN`, `TRIAGED`, `REMEDIATING`, or `REOPENED` — either violation is rejected with `ERR_COMPLAINTS_STILL_OPEN` (HTTP 409). The `legal_hold` flag itself is managed through a dedicated capability taking a boolean `legal_hold` body field that sets or clears it on demand, on an item in any archive status; `dispute_freeze` is never set by hand — it is applied by the complaint cascade and lifted on resolve or dismiss.

## 4. Endpoint Definitions

All endpoints are mounted under `/caption-ad`. Requests that create a new resource answer 201; requests that modify an existing resource answer 200. Every list endpoint paginates per §2.3 and filters by the query parameters named in §3. Every mutating endpoint enforces the validation ordering of §2.4 and the OCC rules of §2.5 where they apply. Path templates use the variables `clientId`, `mediaAssetId`, `workOrderId`, `trackId`, `qcReviewId`, `adTrackId`, `liveEventId`, `stenographerId`, `assignmentId`, `complaintId`, `conversionJobId`, and `archiveItemId`; identifiers in a path resolve from left to right, and the first identifier that fails to resolve yields `ERR_NOT_FOUND`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /caption-ad/clients | Create a client organization | OperationsManager |
| GET | /caption-ad/clients | List clients (filterable by `client_status`) | All roles |
| GET | /caption-ad/clients/{clientId} | Get one client | All roles |
| POST | /caption-ad/clients/{clientId}/suspend | Suspend a client | OperationsManager |
| POST | /caption-ad/clients/{clientId}/reactivate | Reactivate a suspended client | OperationsManager |
| POST | /caption-ad/media-assets | Register a source media asset | IntakeCoordinator |
| GET | /caption-ad/media-assets | List media assets (filterable by `client_id`, `intake_status`) | All roles |
| GET | /caption-ad/media-assets/{mediaAssetId} | Get one media asset | All roles |
| POST | /caption-ad/media-assets/{mediaAssetId}/begin-inspection | Begin technical inspection | IntakeCoordinator |
| POST | /caption-ad/media-assets/{mediaAssetId}/clear | Clear an asset for production | IntakeCoordinator |
| POST | /caption-ad/media-assets/{mediaAssetId}/reject | Reject an asset at intake | IntakeCoordinator |
| POST | /caption-ad/work-orders | Create a work order | IntakeCoordinator |
| GET | /caption-ad/work-orders | List work orders (filterable by `client_id`, `media_asset_id`, `order_status`) | All roles |
| GET | /caption-ad/work-orders/{workOrderId} | Get one work order | All roles |
| POST | /caption-ad/work-orders/{workOrderId}/quote | Quote (or re-quote) a work order | IntakeCoordinator |
| POST | /caption-ad/work-orders/{workOrderId}/confirm | Confirm a quoted order | ClientContact |
| PATCH | /caption-ad/work-orders/{workOrderId} | Amend tier or language (OCC) | IntakeCoordinator |
| POST | /caption-ad/work-orders/{workOrderId}/start-production | Begin production | CaptionEditor |
| POST | /caption-ad/work-orders/{workOrderId}/deliver | Deliver a ready order | OperationsManager |
| POST | /caption-ad/work-orders/{workOrderId}/accept-delivery | Client accepts delivery | ClientContact |
| POST | /caption-ad/work-orders/{workOrderId}/cancel | Cancel an order | IntakeCoordinator, OperationsManager |
| POST | /caption-ad/work-orders/{workOrderId}/caption-tracks | Create a caption track version (OCC) | CaptionEditor |
| GET | /caption-ad/caption-tracks | List caption tracks (filterable by `work_order_id`, `supersedes_track_id`, `track_status`) | All roles |
| GET | /caption-ad/caption-tracks/{trackId} | Get one caption track | All roles |
| POST | /caption-ad/caption-tracks/{trackId}/submit-review | Submit a track for internal review | CaptionEditor |
| POST | /caption-ad/caption-tracks/{trackId}/return-to-authoring | Return a track to authoring | CaptionEditor |
| POST | /caption-ad/caption-tracks/{trackId}/enqueue-qc | Enqueue a track for QC | CaptionEditor |
| POST | /caption-ad/caption-tracks/{trackId}/begin-rework | Begin rework on a failed track | CaptionEditor |
| POST | /caption-ad/caption-tracks/{trackId}/mark-conformed | Mark a passed track conformed | CaptionEditor |
| POST | /caption-ad/caption-tracks/{trackId}/qc-reviews | Finalize an accuracy review | QCSpecialist |
| GET | /caption-ad/qc-reviews | List QC reviews (filterable by `caption_track_id`, `outcome`) | All roles |
| GET | /caption-ad/qc-reviews/{qcReviewId} | Get one QC review | All roles |
| POST | /caption-ad/work-orders/{workOrderId}/audio-description-tracks | Create an AD track | ADProducer |
| GET | /caption-ad/audio-description-tracks | List AD tracks (filterable by `work_order_id`, `ad_status`) | All roles |
| GET | /caption-ad/audio-description-tracks/{adTrackId} | Get one AD track | All roles |
| PATCH | /caption-ad/audio-description-tracks/{adTrackId} | Edit gaps, segments, or narrator while scripting | ADProducer |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/submit-script | Submit the AD script | ADProducer |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/approve-script | Approve the AD script | QCSpecialist |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/reject-script | Reject the AD script | QCSpecialist |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/book-studio | Book studio recording time | ADProducer |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/submit-mix | Submit the recorded mix | ADProducer |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/approve-mix | Approve the mix | QCSpecialist |
| POST | /caption-ad/audio-description-tracks/{adTrackId}/reject-mix | Reject the mix | QCSpecialist |
| POST | /caption-ad/live-events | Schedule a live event | Scheduler |
| GET | /caption-ad/live-events | List live events (filterable by `client_id`, `channel_id`, `event_status`) | All roles |
| GET | /caption-ad/live-events/{liveEventId} | Get one live event | All roles |
| POST | /caption-ad/live-events/{liveEventId}/go-on-air | Take the event on air | Scheduler |
| POST | /caption-ad/live-events/{liveEventId}/wrap | Wrap the event | Scheduler |
| POST | /caption-ad/live-events/{liveEventId}/settle | Settle the event | Scheduler |
| POST | /caption-ad/live-events/{liveEventId}/cancel | Cancel the event | Scheduler |
| POST | /caption-ad/stenographers | Roster a stenographer | Scheduler |
| GET | /caption-ad/stenographers | List stenographers (filterable by `steno_status`, `certification`) | All roles |
| GET | /caption-ad/stenographers/{stenographerId} | Get one stenographer | All roles |
| POST | /caption-ad/stenographers/{stenographerId}/suspend | Suspend a stenographer | Scheduler |
| POST | /caption-ad/stenographers/{stenographerId}/reinstate | Reinstate a stenographer | Scheduler |
| POST | /caption-ad/stenographers/{stenographerId}/renew-certification | Renew a lapsed certification | Scheduler |
| POST | /caption-ad/live-events/{liveEventId}/assignments | Offer an assignment (OCC; auto-offer when stenographer omitted) | Scheduler |
| GET | /caption-ad/live-assignments | List assignments (filterable by `live_event_id`, `stenographer_id`, `assignment_status`) | All roles |
| GET | /caption-ad/live-assignments/{assignmentId} | Get one assignment | All roles |
| POST | /caption-ad/live-assignments/{assignmentId}/accept | Accept an offer | Stenographer |
| POST | /caption-ad/live-assignments/{assignmentId}/decline | Decline an offer | Stenographer |
| POST | /caption-ad/live-assignments/{assignmentId}/check-in | Check in for the event | Stenographer |
| POST | /caption-ad/live-assignments/{assignmentId}/preempt | Preempt an assignment | Scheduler |
| POST | /caption-ad/live-assignments/{assignmentId}/mark-no-show | Mark an assignment no-show | Scheduler |
| POST | /caption-ad/complaints | Open an error complaint | ClientContact |
| GET | /caption-ad/complaints | List complaints (filterable by `client_id`, subject ids, `remediation_track_id`, `complaint_status`) | All roles |
| GET | /caption-ad/complaints/{complaintId} | Get one complaint | All roles |
| POST | /caption-ad/complaints/{complaintId}/triage | Triage a complaint | OperationsManager |
| POST | /caption-ad/complaints/{complaintId}/dismiss | Dismiss a complaint | OperationsManager |
| POST | /caption-ad/complaints/{complaintId}/begin-remediation | Begin remediation | OperationsManager |
| POST | /caption-ad/complaints/{complaintId}/resolve | Resolve a complaint | OperationsManager |
| POST | /caption-ad/complaints/{complaintId}/reopen | Reopen a resolved complaint | ClientContact |
| POST | /caption-ad/conversion-jobs | Queue a format conversion job | OperationsManager, CaptionEditor |
| GET | /caption-ad/conversion-jobs | List conversion jobs (filterable by `source_track_id`, `job_status`) | All roles |
| GET | /caption-ad/conversion-jobs/{conversionJobId} | Get one conversion job | All roles |
| POST | /caption-ad/conversion-jobs/{conversionJobId}/run | Run one conversion pass | OperationsManager |
| POST | /caption-ad/conversion-jobs/{conversionJobId}/retry | Requeue a failed job | OperationsManager |
| POST | /caption-ad/conversion-jobs/{conversionJobId}/cancel | Cancel a queued job | OperationsManager |
| GET | /caption-ad/archive-items | List archive items (filterable by subject ids, `archive_status`) | All roles |
| GET | /caption-ad/archive-items/{archiveItemId} | Get one archive item | All roles |
| POST | /caption-ad/archive-items/{archiveItemId}/cold-store | Move an item to cold storage | OperationsManager |
| POST | /caption-ad/archive-items/{archiveItemId}/request-restore | Request a restore | OperationsManager |
| POST | /caption-ad/archive-items/{archiveItemId}/complete-restore | Complete a restore | OperationsManager |
| POST | /caption-ad/archive-items/{archiveItemId}/rearchive | Return a restored item to cold storage | OperationsManager |
| POST | /caption-ad/archive-items/{archiveItemId}/purge | Purge an item past retention | OperationsManager |
| POST | /caption-ad/archive-items/{archiveItemId}/set-legal-hold | Set or clear a legal hold | OperationsManager |
| POST | /caption-ad/_clock/set_current_utc | Set the logical clock | OperationsManager |
| POST | /caption-ad/_ops/run-sweep | Run the ops sweep checkpoint | OperationsManager |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED_ROLE | 403 |
| ERR_FORBIDDEN_OWNERSHIP | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_VALIDATION | 400 |
| ERR_STALE_WORK_ORDER_VERSION | 412 |
| ERR_STALE_LIVE_EVENT_VERSION | 412 |
| ERR_INVALID_TRANSITION | 409 |
| ERR_SEGREGATION_OF_DUTIES | 403 |
| ERR_REVIEW_MODE_NOT_PERMITTED | 422 |
| ERR_ARCHIVE_LEGAL_HOLD | 409 |
| ERR_QUOTE_EXPIRED | 409 |
| ERR_OFFER_EXPIRED | 409 |
| ERR_CHECKIN_WINDOW_CLOSED | 409 |
| ERR_COMPLAINT_WINDOW_CLOSED | 409 |
| ERR_REOPEN_WINDOW_CLOSED | 409 |
| ERR_TIER_DURATION_INCOMPATIBLE | 422 |
| ERR_STENOGRAPHER_DOUBLE_BOOKED | 409 |
| ERR_CAPACITY_EXCEEDED | 422 |
| ERR_STUDIO_TURNOVER_VIOLATION | 409 |
| ERR_GAP_COVERAGE_OUT_OF_BAND | 422 |
| ERR_COMPLAINT_ALREADY_OPEN | 409 |
| ERR_CONVERSION_SAME_FORMAT | 422 |
| ERR_EMBED_NOT_SUPPORTED | 422 |
| ERR_NO_ELIGIBLE_STENOGRAPHER | 422 |
| ERR_RETRY_LIMIT_REACHED | 409 |
| ERR_CLIENT_NOT_ACTIVE | 409 |
| ERR_MEDIA_NOT_CLEARED | 409 |
| ERR_SOURCE_TRACK_NOT_FINAL | 409 |
| ERR_GO_ON_AIR_BLOCKED | 409 |
| ERR_COMPLAINTS_STILL_OPEN | 409 |
| ERR_RETENTION_NOT_ELAPSED | 409 |
| ERR_RESOLUTION_ARTIFACT_INCOMPLETE | 409 |
