# Massage Therapy Practice API — Product Requirements Document

## 1. Introduction

This document specifies the backend service that runs a multi-therapist massage therapy practice end to end: it tracks who is licensed and certified to deliver which kinds of bodywork, which rooms and tables are free at any given moment, what each client has consented to and been screened for, and how every session is scheduled, documented clinically, priced, and ultimately paid. The practice mixes several payment realities at once — cash and card walk-ins, members redeeming monthly session credits, clients spending health-savings funds, and patients who need an insurance superbill — and the service must reconcile all of them against a single appointment record without ever double-charging or losing a credit.

Two pressures shape almost every rule here. The first is *time*: licenses expire, intakes go stale, membership cycles renew, late cancellations and no-shows are penalized on a sliding scale, and the entire system reads a single server-controlled logical clock so that these temporal effects are reproducible rather than dependent on wall-clock time. The second is *money owed to the right party*: each completed session must compute a service charge, settle the client's portion through the correct payment waterfall, and then credit the assigned therapist the correct commission and gratuity. Because the practice's busiest tables are booked concurrently by reception staff, the booking path is additionally guarded by optimistic concurrency control so that two front-desk operators working from a stale view of a table cannot wedge overlapping sessions onto it.

The reader should treat this as a contract. Field names, state values, error identifiers, ordering of validation checks, rounding behavior, and the precise side effects of each transition are all normative. Where a calculation is described in prose, the prose is the specification — it is written so that the exact arithmetic can be reconstructed from it.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request is authenticated and authorized by two headers. `X-User-ID` carries the caller's identifier and `X-User-Role` carries the caller's role. If `X-User-Role` is missing or is not one of the four roles defined below, or if `X-User-ID` is missing for a role whose identity is tied to a persisted entity, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). When the role and identity are present and well-formed but the role is not permitted to invoke the requested operation — or an entity-backed caller attempts to act on a resource it does not own — the request is rejected with `ERR_UNAUTHORIZED` (HTTP 403). There is one carve-out: a non-owning `Therapist` or `Client` that fetches a single appointment (`GET /practice/appointments/{id}`) or a single SOAP note (`GET /practice/soap-notes/{id}`) it does not own is answered with `ERR_NOT_FOUND` (HTTP 404) rather than `ERR_UNAUTHORIZED`, so the resource's existence is not disclosed; ownership-violating reads of all other resource types (clients, intakes, consent records, packages, package ledgers, superbills) return `ERR_UNAUTHORIZED` (HTTP 403).

The four roles are spelled exactly `PracticeAdmin`, `FrontDesk`, `Therapist`, and `Client`.

When `X-User-Role` is `PracticeAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it but never compares it to any entity's `id`. The same holds for `FrontDesk`: its `X-User-ID` is an opaque operator identifier, recorded if useful but never matched against an entity's `id`. A `PracticeAdmin` is the practice owner/manager — it configures modalities, membership plans, tables, commission tiers, and certifications, and it alone drives renewals, suspensions, membership cancellations, voids, no-show waivers, and the logical clock. A `FrontDesk` operator is reception staff — registering clients, booking and checking in sessions, cancelling and marking no-shows, pricing and collecting payment, and issuing superbills.

When `X-User-Role` is `Therapist`, `X-User-ID` is the `id` of the acting `Therapist`; ownership checks on any resource that references a `Therapist` compare the resource's therapist foreign key to `X-User-ID`. In particular, only the therapist assigned to an appointment may finalize that appointment's clinical note. When `X-User-Role` is `Client`, `X-User-ID` is the `id` of the acting `Client`; ownership checks on any resource that references a `Client` compare the resource's client foreign key to `X-User-ID`. A `Client` may sign only its own intake, may revoke only its own consent, and may read only its own client record, appointments, packages, and superbills.

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

List endpoints accept two pagination query parameters, `limit` and `offset`. `limit` defaults to 10 when omitted, may be no smaller than 1 and no larger than 100. `offset` defaults to 0 and may not be negative. A request whose `limit` or `offset` falls outside these bounds is a malformed request and is rejected with `ERR_INVALID_REQUEST` (HTTP 422).

Unless a specific endpoint says otherwise, lists are returned sorted by `created_at` in ascending order (oldest first); when two records carry the identical `created_at` (because both were written at the same logical-clock instant), the tie is broken by insertion order — the order in which the records were created — so the oldest-created record sorts first. The `meta` object of a list response reports `limit`, `offset`, `total_count` (the total number of matching records before the page window is applied), and `has_more` (true exactly when `offset + (number of records on this page) < total_count`).

### 2.4. Common Resource Properties, Timestamps, and Versioning

Every resource is identified by an `id` that is a server-minted UUID with no type prefix; clients never supply it. Most resources also carry three further system-managed fields: `created_at` and `updated_at`, both ISO 8601 UTC timestamps with three fractional digits, and `version`, an integer that begins at 1 when the resource is created and increments by exactly 1 on every successful mutation of that resource. The `created_at` value is fixed at creation; `updated_at` is refreshed to the logical clock instant of every mutation that bumps `version`.

There is one deliberate exception. A `CreditLedgerEntry` is an append-only audit record and carries only `id` and `created_at`; it has no `updated_at` and no `version`, because it is never mutated after it is written. Every other entity in this system — `Modality`, `Therapist`, `TherapistCertification`, `Table`, `Client`, `Intake`, `ConsentRecord`, `MembershipPlan`, `Package`, `CommissionTier`, `Appointment`, `SoapNote`, and `Superbill` — carries the full `id`, `created_at`, `updated_at`, and `version` set.

### 2.5. The Logical Clock

All time-dependent behavior reads a single server-wide logical clock rather than wall-clock time. The server starts with the logical clock fixed at `2026-01-01T00:00:00Z`; before any clock-setting call is made, the clock reads exactly this default and never falls back to the host's real time. A `PracticeAdmin` may set the clock to any explicit UTC instant by supplying a `to_iso8601` value; the clock may be advanced or rewound, and the call returns HTTP 200 with `data` set to an object carrying a single `now` field holding the new clock instant as an ISO 8601 UTC string (i.e. `data: {"now": "<instant>"}`). Every license and certification expiry, intake staleness, membership cycle end, check-in and no-show window, and no-show lead-time proration is evaluated against this clock's current value.

### 2.6. Money, Precision, and Rounding

All monetary amounts are stored and exchanged as integer cents; all session-credit amounts are stored as integer counts of sessions. Wherever a calculation in this document multiplies cents by a fraction (a discount rate, a commission rate, a fee fraction, or a strike multiplier), the multiplication is carried in exact rational arithmetic and rounding to whole cents is applied exactly once, at the pinned final step of that calculation — never tier-by-tier or line-by-line before the chain completes. The rounding method is round half up (a value exactly halfway between two cents rounds to the larger cent). Pure session-credit arithmetic involves only integers and is never rounded.

### 2.7. Soft Deletion and Default List Visibility

`Modality`, `Table`, `MembershipPlan`, and `CommissionTier` records carry an `archived` flag that is `false` at creation and acts as a soft delete. Archived records are hidden from default list responses and cannot be assigned to new appointments (an archived table additionally rejects new bookings). List endpoints for these collections accept an `include_archived` flag; when it is set, archived records are included in the result.

### 2.8. Optimistic Concurrency on Table Booking

Booking an appointment is the one write in this system guarded by optimistic concurrency control, and the contested resource is the `Table`. A booking request must carry `expected_table_version`, which is a required (non-optional) field carrying the client's last observed `version` of the target table. The server compares it to the table's current `version`; if they do not match — because a prior booking against that same table has since advanced the table's `version` and thereby changed its occupied-interval set — the booking is rejected with `ERR_STALE_VERSION` (HTTP 412). The rejection means the caller's view of the table is stale and proceeding could place a colliding interval, so the caller must re-read the table and retry with the fresh `version`. A successful booking itself advances the table's `version` by 1, which is what makes it the concurrency anchor for the next writer. No other write endpoint in this system takes a version field on its parent.

### 2.9. Referenced-Resource Existence and Path Resolution

Whenever a request names another resource — through a path identifier such as the `{id}` segment, or through a foreign-key body field such as `client_id`, `therapist_id`, `table_id`, `modality_id`, `consent_id`, `package_id`, `plan_id`, or `appointment_id` — that resource must exist. References are resolved left to right, the path identifier first and then the body fields in the order listed, and the first reference that does not resolve yields `ERR_NOT_FOUND` (HTTP 404). List endpoints support reverse lookup: appointments may be filtered by any of their foreign keys, intakes/consent-records/packages by `client_id`, certifications by `therapist_id`, ledger entries by their owning package, SOAP notes by `appointment_id`, and superbills by `appointment_id` or `client_id`.

### 2.10. Validation Ordering

When several checks could fail on one request, they are evaluated in a fixed priority order so that the returned error is deterministic. The global ordering, highest priority first, is: authentication (`ERR_UNAUTHENTICATED`), then authorization (`ERR_UNAUTHORIZED`), then existence of referenced resources (`ERR_NOT_FOUND`), then request well-formedness — required fields present, enums valid, integers within their declared ranges (`ERR_INVALID_REQUEST`), then the state-machine precondition that the target is in a state from which the transition is legal (`ERR_INVALID_STATE`), then, on booking only, the table optimistic-concurrency check (`ERR_STALE_VERSION`). Only after all of those pass are the domain-specific booking gates evaluated, themselves in a fixed order described in §3.4. The practical consequence is that a malformed body is reported before any business gate runs, and a wrong-state transition is reported before the booking's safety and fiscal gates are even consulted.

## 3. Business Logic & Workflows

### 3.1. Configuring the Practice: Modalities, Therapists, Certifications, Tables, Plans, and Tiers

Before any session can be booked, a `PracticeAdmin` stands up the practice's catalog. A **modality** is a kind of bodywork — Swedish, Deep Tissue, Prenatal, Lymphatic, and so on. Each modality carries a `name` that must be unique (case-insensitively) among non-archived modalities, and a short uppercase `code` of two to eight letters that is unique across all modalities and immutable once set. A modality's `base_price_cents` is the list price for a sixty-minute session and may not be negative. When `requires_certification` is true (it defaults to false), only a therapist holding an active certification for this modality's `code` may be assigned to its sessions. A modality may also declare `contraindication_tags` — a list (empty by default) of risk tags such as PREGNANCY, HYPERTENSION, or RECENT_SURGERY — that block booking when they collide with a client's declared risks. Modalities carry an `archived` flag governed by §2.7.

A **therapist** is created with a `full_name` and a `license_number` that must match the pattern of the two letters `LMT-` followed by exactly six digits, is unique across all therapists, and is immutable after creation. The therapist's `license_expiry` is the UTC instant the license lapses; the derived `license_status` reads `ACTIVE` while `license_expiry` is strictly after the clock's current value and `LICENSE_EXPIRED` once `license_expiry` is at or before the clock. A therapist's `commission_scheme` is either `FLAT` or `TIERED` (defaulting to `TIERED`); when it is `FLAT`, the `flat_commission_pct` fraction (between 0 and 1 inclusive, default 0.40) is the single commission rate. Two further fields are accumulators the system maintains rather than the admin: `mtd_service_revenue_cents` is the therapist's month-to-date service revenue used to place them on the commission schedule, and `accrued_commission_cents` is the running total of commission plus gratuity credited this commission month; both default to 0. A `PracticeAdmin` may begin a fresh commission month by resetting the therapist's accumulators, which sets both `mtd_service_revenue_cents` and `accrued_commission_cents` back to 0 and bumps the therapist's `version`.

A **certification** ties a therapist to a modality. It records `therapist_id`, the `modality_code` it authorizes (which must equal the `code` of a non-archived modality), and a `cert_expiry` instant. Its derived `cert_status` is `ACTIVE` while the clock is strictly before `cert_expiry` and `EXPIRED` once the clock is at or after `cert_expiry`; only an `ACTIVE` certification satisfies a modality's certification gate.

A **table** is a physical table/room with a `label` unique among non-archived tables and a `room` grouping. Its `turnover_buffer_minutes` (default 15, at least 0 and at most 120) is the minimum cleaning gap the table needs between the end of one session and the start of the next; two sessions whose intervals on this table sit closer together than this buffer collide. When `supports_prenatal` is false, a session whose modality `code` is `PRENATAL` cannot be placed on this table. Tables carry an `archived` flag per §2.7.

A **membership plan** defines a recurring offering: a `name` unique among non-archived plans, a `monthly_fee_cents` that is non-negative, an `included_sessions` count of at least 1 granted each billing cycle, a `member_discount_pct` fraction (between 0 and 1 inclusive, default 0.15) applied to out-of-pocket sessions and add-ons beyond the included credits, and a `rollover_cap_sessions` (default 1, at least 0) limiting how many unused credits survive into the next cycle. Plans carry an `archived` flag.

Finally, the **commission schedule** is a set of global `CommissionTier` rows used by every `TIERED` therapist. Each tier has a `tier_index`, a zero-based ordering position that is unique among non-archived tiers and at least 0; a `floor_revenue_cents` that is the inclusive lower bound (at or above which the tier's rate begins to apply marginally) and is non-negative; and a `commission_pct` fraction (between 0 and 1 inclusive) applied to the slice of month-to-date revenue at or above this tier's floor and below the next tier's floor. Tiers carry an `archived` flag and default lists exclude archived tiers and present them sorted by `tier_index`.

### 3.2. Onboarding a Client: Registration, Intake, and Consent

A client is registered by `FrontDesk` or `PracticeAdmin` with a `full_name` and an `email` that matches a basic email pattern and is unique among non-archived clients; an opening `hsa_balance_cents` (non-negative, default 0) may be supplied. The system also maintains three computed fields on the client: `wallet_credit_cents` is a store-credit balance (default 0) that is spent before card charges at settlement; `no_show_strikes` (default 0) counts recent no-shows within the strike window; and an `archived` soft-delete flag. A `PracticeAdmin` may directly adjust a client's store credit by supplying a `delta_cents` amount; the client's `wallet_credit_cents` moves by that signed amount but is floored at 0 (it can never go negative), and the client's `version` is bumped.

Before a client may be booked, two clinical preconditions must be satisfied. The first is an **intake**. An intake is created (by the client, front desk, or admin) against a `client_id` with an `expires_at` instant and an optional list of `risk_flags` — the contraindication risks the client declares, such as PREGNANCY or HYPERTENSION. A new intake begins in `intake_status` `DRAFT`, with `signed_at` null. The client signs their own intake, which moves it to `ACTIVE` and stamps `signed_at` with the clock's current instant; this is allowed only while the intake is `DRAFT` and only when the acting client owns the intake. Signing a new intake supersedes any prior intake the client already had in `ACTIVE` status: that earlier intake transitions to `SUPERSEDED`, and its own `version` is bumped as part of that transition. Only an intake that is currently `ACTIVE` and whose `expires_at` is strictly after the clock satisfies the booking precondition; an `ACTIVE` intake whose `expires_at` has reached or passed the clock is stale and does not count.

The second precondition is **consent**. A consent record is created against a `client_id` with a `draping_policy` of `FULL_DRAPE`, `PARTIAL_DRAPE`, or `DECLINE_TREATMENT`, and a `sensitive_area_consent` boolean (default false) indicating whether the client agrees to glute/abdominal work. A consent record begins in `consent_status` `ACTIVE`. A client may revoke their own consent, moving it to `REVOKED`; revoking is allowed only from `ACTIVE` and only by the owning client. Revoking consent that a live session still depends on cascades: every appointment referencing that consent whose `scheduling_status` is `SCHEDULED` or `CHECKED_IN` is cancelled with `cancel_reason` `CONSENT_REVOKED`, carries no fee, and — if a membership credit had been redeemed for it — has that credit refunded to the package, which in turn recomputes the package's credit balance. A consent whose `draping_policy` is `DECLINE_TREATMENT` can never be used to book.

### 3.3. Pre-Booking Safety Gates: Consent, Contraindication, Intake, License, Certification

Booking is the most heavily guarded operation in the practice because it is where every safety and eligibility rule converges. The gates below are described here so that the front-desk workflow in §3.4 can reference them by name; each gate names the error it raises, and the relative order in which they fire is fixed in §3.4.

The **consent gate** requires that the referenced consent be `ACTIVE`, that its `draping_policy` is not `DECLINE_TREATMENT`, and that — for a modality the practice treats as sensitive, namely a modality carrying the `DEEP_TISSUE` tag — the consent's `sensitive_area_consent` is true. Any of these failing raises `ERR_CONSENT_REQUIRED`. This same gate is re-evaluated at check-in: a session cannot be checked in if its consent is no longer active.

The **contraindication gate** compares the modality's `contraindication_tags` against the client's currently `ACTIVE` intake's `risk_flags`. For each tag present in both, there must exist a finalized clinical note (a `SoapNote` in `FINALIZED` or `AMENDED` status) that has cleared that tag for this client; if any matching tag lacks such a clearing note, booking is blocked with `ERR_CONTRAINDICATION`.

The **intake gate** requires the client to have an intake that is `ACTIVE` and whose `expires_at` is strictly after the clock; failing this raises `ERR_INTAKE_INVALID`.

The **license gate** requires the assigned therapist's `license_status` to be `ACTIVE` — equivalently, `license_expiry` strictly after the clock — and it is enforced both at booking and at check-in; a lapsed license raises `ERR_LICENSE_EXPIRED`.

The **certification gate** applies only when the chosen modality has `requires_certification` true: the assigned therapist must then hold a `TherapistCertification` whose `modality_code` matches the modality's `code` and whose `cert_status` is `ACTIVE`. Absent such a certification, booking is blocked with `ERR_CERTIFICATION_REQUIRED`.

### 3.4. Booking a Session and Holding the Slot

Booking an appointment is performed by `FrontDesk` or `PracticeAdmin`. The request names the participants and resources through `client_id`, `therapist_id`, `table_id`, `modality_id`, and `consent_id`, an optional `package_id` (set only when the session will be redeemed against a membership), a `start_at` instant, an optional `duration_minutes` (one of 30, 60, 90, or 120; default 60), an optional `payer` (one of `CASH`, `HSA`, or `MEMBERSHIP`; default `CASH`), an optional `gratuity_cents` (non-negative, default 0), and the required `expected_table_version` described in §2.8. The session's `end_at` is computed as the `start_at` advanced by `duration_minutes`, and the half-open interval from `start_at` up to `end_at` is what the table is considered to occupy. A booked appointment begins with `scheduling_status` `SCHEDULED` and `settlement_status` `UNSETTLED`, with `cancel_reason` null and `service_charge_cents`, `client_owed_cents`, `no_show_fee_cents`, and `commission_credited_cents` all initialized to 0, and a successful booking advances the table's `version` by 1. Throughout this document, an appointment counts as **non-terminal** (and therefore still occupies its table interval and its therapist's time for the overlap gates) exactly while its `scheduling_status` is one of `SCHEDULED`, `CHECKED_IN`, or `COMPLETED`; once its `scheduling_status` is `CANCELLED` or `NO_SHOW` it is terminal and no longer participates in any overlap check. Non-terminality is keyed on `scheduling_status` alone, so a `COMPLETED` appointment continues to occupy its slot for overlap purposes regardless of its `settlement_status` (including after it has been voided).

The gates run in a fixed sequence. After the global checks of §2.10 (authentication, authorization, existence of every referenced resource, request well-formedness, and then — for booking specifically — the `expected_table_version` optimistic-concurrency check that raises `ERR_STALE_VERSION` on a stale table), the domain gates fire in this order: first the consent gate (`ERR_CONSENT_REQUIRED`), then the contraindication gate (`ERR_CONTRAINDICATION`), then the intake gate (`ERR_INTAKE_INVALID`), then the license gate (`ERR_LICENSE_EXPIRED`), then the certification gate (`ERR_CERTIFICATION_REQUIRED`), then the table-suitability gate, then the table-overlap gate, and finally the therapist-overlap gate. Because the order is fixed, a session that violates several gates surfaces the highest-priority violation only.

The **table-suitability gate** rejects a `PRENATAL` modality on a table whose `supports_prenatal` is false, and rejects any booking onto an archived table, with `ERR_TABLE_UNSUITABLE`. The **table-overlap gate** then checks the requested interval, extended by the table's `turnover_buffer_minutes` on both ends (so the comparison interval runs from `start_at` minus the buffer to `end_at` plus the buffer), against the raw `[start_at, end_at)` interval of every non-terminal appointment already on that same table; a collision occurs exactly when the buffer-extended request interval and the existing raw interval overlap under half-open semantics (`request_start_minus_buffer < existing_end` and `existing_start < request_end_plus_buffer`). The practical consequence is that two sessions separated by a gap strictly smaller than the buffer collide, while a gap equal to or larger than the buffer (including two sessions buffer-apart exactly) is allowed; a collision is rejected with `ERR_TABLE_DOUBLE_BOOKED`. The **therapist-overlap gate** finally checks the requested interval against every other non-terminal appointment for the same therapist; here there is no buffer and the comparison uses the same half-open overlap test (`request_start < existing_end` and `existing_start < request_end`), so two sessions that merely touch end-to-start are allowed, but any genuine overlap raises `ERR_THERAPIST_DOUBLE_BOOKED`. When the booking's `payer` is `MEMBERSHIP`, no credit is debited at booking time — the credit is held and only redeemed later, at pricing.

### 3.5. Running the Session: Check-In, Clinical Documentation, and Completion

On the day of the session a `FrontDesk` operator checks the client in. Check-in is allowed only while `scheduling_status` is `SCHEDULED`, only while the clock is strictly before the session's `end_at` (a session cannot be checked in after its window has fully elapsed), only while the assigned therapist's license is `ACTIVE` at the current clock, and only while the governing consent is still `ACTIVE`. These conditions are evaluated in that listed order and raise, respectively, `ERR_INVALID_STATE` (not `SCHEDULED`), `ERR_INVALID_STATE` (window already elapsed, i.e. clock at or after `end_at`), `ERR_LICENSE_EXPIRED` (lapsed license), and `ERR_CONSENT_REQUIRED` (consent no longer `ACTIVE`). A successful check-in advances `scheduling_status` from `SCHEDULED` to `CHECKED_IN`.

During or after the session the assigned **therapist** documents care in a SOAP note. A note is created against an `appointment_id` and carries the four narrative fields `subjective` (the client-reported symptoms), `objective` (the therapist's findings), `assessment`, and `plan`, plus an optional `clears_contraindication_tags` list naming any contraindication tags this note clears for the client. All four narrative fields are optional at create time and each defaults to the empty string when omitted or null (`clears_contraindication_tags` likewise defaults to an empty list); only the acting therapist assigned to the appointment may create the note, and a caller who is not the assigned therapist is rejected with `ERR_UNAUTHORIZED`. A new note begins in `note_status` `DRAFT`. While `DRAFT`, the note's `subjective`, `objective`, `assessment`, `plan`, and `clears_contraindication_tags` may be edited; an edit must carry `expected_soap_note_version` matching the note's current `version`, and a successful edit bumps that `version`. The checks fire in this order: the `expected_soap_note_version` field must be present (else `ERR_INVALID_REQUEST`), then the note must be in `DRAFT` (else `ERR_INVALID_STATE`), and only then is the version compared (a mismatch raises `ERR_STALE_VERSION`); thus a non-`DRAFT` note reports `ERR_INVALID_STATE` even when the supplied version is also wrong. On a successful edit only the narrative and clears fields explicitly supplied (and non-null) are overwritten; omitted fields are left unchanged.

The assigned therapist finalizes the note. Finalizing is permitted only while the note is `DRAFT`, only when all four of `subjective`, `objective`, `assessment`, and `plan` are non-empty, and only when the acting therapist is the one assigned to the appointment. The first finalize of a never-before-finalized note moves it to `FINALIZED`; finalizing a note that had previously been finalized and then reopened moves it instead to `AMENDED`. Either way, every tag listed in the note's `clears_contraindication_tags` is recorded as cleared for the client, which unblocks future bookings of modalities carrying those tags. A finalized note may be reopened by the therapist back to `DRAFT` for amendment, but only while its linked appointment's `settlement_status` is not yet `PAID`; reopening revokes the contraindication clearances this note had granted (un-clearing exactly the tags it had cleared). When the note is re-finalized from that reopened `DRAFT` state — the `AMENDED` outcome — those clearances are re-applied. For the purpose of completing the appointment, an `AMENDED` note counts as finalized exactly as a `FINALIZED` one does.

Completion is the bridge from documentation to settlement. A `Therapist` or `FrontDesk` operator completes the session, which is allowed only while `scheduling_status` is `CHECKED_IN` and only when a SOAP note for this appointment exists in `FINALIZED` or `AMENDED` status; a wrong scheduling state and a missing finalized note are both reported as `ERR_INVALID_STATE` (the `CHECKED_IN` check is evaluated first). A completing `Therapist` who is not the one assigned to the appointment is answered with `ERR_NOT_FOUND` (HTTP 404). Completion advances `scheduling_status` from `CHECKED_IN` to `COMPLETED`.

### 3.6. Cancellations, No-Shows, and the Strike System

Not every booked session is delivered, and the practice distinguishes a polite cancellation from a missed appointment. A cancellation, performed by `FrontDesk` or `PracticeAdmin`, requires a `cancel_reason` of `CLIENT_REQUEST`, `LATE_CANCEL`, `CONSENT_REVOKED`, or `PRACTICE_CANCEL`, and is allowed while the session is either `SCHEDULED` or `CHECKED_IN`. Cancelling sets `scheduling_status` to `CANCELLED` and releases the table interval so the slot frees up. If the session had redeemed a membership credit, cancellation writes a refund ledger entry (a `CreditLedgerEntry` with reason `REFUND` and a delta of plus one session) against the package and recomputes the package's `credit_balance_sessions`. Whether a cancellation costs the client anything depends on lead time, where the free-cancellation cutoff sits exactly 1440 minutes (24 hours) before `start_at`: a cancellation whose lead time (computed exactly as in §3.7) is strictly less than 1440 minutes is treated as a *late cancel* and is priced through the late-cancel proration (described in §3.7), setting `settlement_status` to `PRICED` and recording the computed fee in `no_show_fee_cents` while leaving `client_owed_cents` at 0 (a late cancel sets only `no_show_fee_cents`, not `client_owed_cents`); a cancellation whose lead time is 1440 minutes or more carries `no_show_fee_cents` of 0 and leaves `settlement_status` untouched at `UNSETTLED`. Either way the cancelled appointment's `version` is bumped, but the client's `version` is not.

A **no-show** is recorded by `FrontDesk` or `PracticeAdmin` when the client simply does not appear; it is permitted from either `SCHEDULED` or `CHECKED_IN`, but only once the clock has reached or passed `start_at` (a session cannot be marked no-show before its slot has begun). Marking a no-show sets `scheduling_status` to `NO_SHOW`, increments the client's `no_show_strikes` by 1, and — using the strike count as just incremented — computes `no_show_fee_cents` through the no-show proration of §3.7. It then sets `settlement_status` to `PRICED` with `service_charge_cents` of 0 and `client_owed_cents` equal to the computed `no_show_fee_cents`, refunds a redeemed membership credit exactly as cancellation does, releases the table interval, and bumps both the appointment's and the client's `version`.

A `PracticeAdmin` may waive a no-show. Waiving is permitted only while `scheduling_status` is `NO_SHOW` and only while `settlement_status` is not `PAID` — a fee already collected cannot be waived. Waiving is the system's compensating revert: it re-opens the session by setting `scheduling_status` back to `SCHEDULED`, decrements the client's `no_show_strikes` by 1 (never below 0), and undoes the priced fee by setting `settlement_status` back to `UNSETTLED` with `no_show_fee_cents` and `client_owed_cents` both reset to 0. The invariant the practice cares about is that strikes minus waives nets to zero across a no-show followed by its waiver, so the strike the no-show added is exactly the strike the waiver removes.

### 3.7. Pricing the No-Show / Late-Cancel Fee

The fee charged for a missed or late-cancelled session is a fraction of the session's value, scaled by how chronically the client has been missing appointments. Begin with the session's base value: the modality's `base_price_cents` multiplied by `duration_minutes` divided by 60, kept as an exact rational. Then determine the *lead time* in minutes as the start instant minus the current clock instant, expressed in minutes — a positive number when the action happens before the slot, zero or negative for a true no-show whose mark necessarily comes at or after `start_at`. The lead time is computed by taking the elapsed difference in whole seconds (any fractional second truncated toward zero) and dividing that integer count of seconds by 60 as an exact rational, so a lead time that lands between two whole minutes keeps its fractional-minute remainder when it is compared against the band boundaries below.

The fee fraction is a four-band ladder keyed on lead time. When lead time is at least 1440 minutes (that is, 24 hours or more before the start), the fraction is 0 — no fee. When lead time is at least 120 minutes but less than 1440, the fraction is 0.50. When lead time is greater than 0 but less than 120, the fraction is 0.75. When lead time is 0 or negative, the fraction is 1.00 — the full session value. The band boundaries are inclusive at their lower edge: a lead time of exactly 1440 minutes takes the 0 band, and a lead time of exactly 120 minutes takes the 0.50 band.

A strike multiplier then scales the result. When the client's `no_show_strikes` is at least 3, the multiplier is 1.50; otherwise it is 1.00. (For a true no-show the strike count used is the value *after* this no-show's increment, so the third strike — `no_show_strikes` equal to 3 — is the one that first triggers the penalized rate; for a late cancel the strike count is read before any increment, since a cancel does not add a strike.) The raw fee is the base session value multiplied by the fee fraction and then by the strike multiplier, all in exact rational arithmetic; `no_show_fee_cents` is that product rounded half up to whole cents exactly once, after the full multiply chain. A late cancel always falls in a positive-lead band (0.50 or 0.75 — never 1.00, since its lead time is positive), whereas a true no-show always lands in the full 1.00 band.

### 3.8. Settling the Session: Pricing the Service and the Payment Waterfall

A completed session is priced by `FrontDesk` or `PracticeAdmin`. Pricing is allowed only while `settlement_status` is `UNSETTLED` and only while `scheduling_status` is `COMPLETED`; a no-show's pricing is automatic at the no-show transition and does not go through this path. Pricing first computes the `service_charge_cents`, then resolves what the client actually owes, and may redeem a membership credit.

The **service charge** depends on the payer and the membership context. Start from the base value: the modality's `base_price_cents` multiplied by `duration_minutes` divided by 60, kept exact. If the payer is `MEMBERSHIP`, the session is paid by redeeming a credit rather than charging money, so `service_charge_cents` is 0. If instead the payer is `CASH` or `HSA` and the appointment's `package_id` references a package that is currently `ACTIVE` and owned by this same client, the session is an out-of-pocket session for an active member and the member discount applies: multiply the base value by one minus the plan's `member_discount_pct`, then round half up to whole cents — the multiply happens first and the rounding happens once, at the end. Otherwise (a `CASH` or `HSA` session with no active membership attached), `service_charge_cents` is simply the base value rounded half up. For illustration, a 12000-cent base under a 0.20 member discount yields a 9600-cent service charge.

Once the service charge is known, the **payment waterfall** sets `client_owed_cents`. The buckets are applied in a fixed order of precedence: membership redemption first (already handled inside pricing, since a `MEMBERSHIP` session has a service charge of 0), then store credit, then the remainder owed. Concretely, the amount owed begins as the `service_charge_cents`; the wallet contribution applied is the smaller of the client's `wallet_credit_cents` and that owed amount; the owed amount is reduced by the wallet contribution; and `client_owed_cents` is the remainder. All of these are integer-cent amounts and no rounding is needed. The wallet contribution is merely recorded at pricing time — the client's `wallet_credit_cents` is not actually decremented until payment, so a session that is voided before payment leaves the wallet untouched.

When the payer is `MEMBERSHIP`, pricing also redeems the credit: provided a credit has not already been debited for this appointment, it writes a `CreditLedgerEntry` with reason `REDEEM` and a delta of minus one session against the package and recomputes the package's `credit_balance_sessions`. Pricing concludes by setting `settlement_status` to `PRICED`.

### 3.9. Taking Payment, Crediting the Therapist, and Voids

Payment of a priced session is taken by `FrontDesk` or `PracticeAdmin` and is allowed only while `settlement_status` is `PRICED`. The payment request may carry a `gratuity_cents` value that overrides whatever gratuity was captured at booking. If the payer is `HSA`, the client's `hsa_balance_cents` must be at least the `client_owed_cents` — otherwise payment is rejected with `ERR_INSUFFICIENT_HSA` — and on success that balance is decremented by `client_owed_cents`. If wallet credit was applied during pricing, the client's `wallet_credit_cents` is now decremented by that applied amount. Payment then moves `settlement_status` to `PAID`.

Payment is also where the assigned therapist is paid. The session's `service_charge_cents` is added to the therapist's `mtd_service_revenue_cents`, and the commission for this session, `commission_credited_cents`, is computed over the revenue band this session occupies and added — together with the full gratuity — to the therapist's `accrued_commission_cents`. Gratuity is paid to the therapist in full but is deliberately excluded from the commission base.

The commission itself follows the therapist's `commission_scheme`. Under a `FLAT` scheme, `commission_credited_cents` is the session's `service_charge_cents` multiplied by the therapist's `flat_commission_pct`, rounded half up to whole cents. Under a `TIERED` scheme, commission is *marginal* across the global commission schedule. Take the non-archived `CommissionTier` rows sorted by `tier_index` ascending (breaking ties by `floor_revenue_cents` ascending and then by `created_at` ascending). Let the old revenue be the therapist's `mtd_service_revenue_cents` before this session and the new revenue be that value plus this session's `service_charge_cents`. For each tier in order, its band runs from its own `floor_revenue_cents` up to the next tier's `floor_revenue_cents` (and the last tier's band extends without upper bound). The portion of the interval from old revenue up to new revenue that lands inside a given tier's band is the larger of zero and (the smaller of new revenue and the band's upper edge) minus (the larger of old revenue and the band's lower edge); that slice is multiplied by the tier's `commission_pct`. These per-tier slice products are summed in exact rational arithmetic across all tiers, and only the final sum is rounded half up to whole cents — never tier by tier. If no non-archived tiers exist, that sum is empty and `commission_credited_cents` is 0. Under either scheme, a session whose `service_charge_cents` is 0 or negative (notably a `MEMBERSHIP` session, whose service charge is 0) earns `commission_credited_cents` of 0 before any tier or flat-rate arithmetic is consulted. Because the calculation depends on where `mtd_service_revenue_cents` already sits, the identical `service_charge_cents` can earn different commission on two different sessions.

A `PracticeAdmin` may **void** a settlement that has not been paid. Voiding is allowed only while `settlement_status` is `UNSETTLED` or `PRICED` and moves it to `VOID`; a `PAID` session cannot be voided (the attempt is rejected with `ERR_INVALID_STATE`), and `scheduling_status` is left unchanged by a void. If the session being voided had redeemed a membership credit at pricing, the void compensates by writing a `REFUND` ledger entry (delta plus one session) against the package and recomputing its `credit_balance_sessions`. Because only `UNSETTLED` or `PRICED` sessions are voidable and a superbill can only ever attach to a `PAID` session, a void never has a superbill attached to it and the void path performs no superbill cascade at all.

### 3.10. Memberships: Credits, Renewal Rollover, Suspension, and Cancellation

A **package** is a client's live membership: it names the `client_id` and the `plan_id` it instantiates, tracks `credit_balance_sessions` (the unused session credits available to spend), a `cycle_anchor_day` (the day-of-month between 1 and 28 on which the membership renews, default 1), a computed `current_cycle_end` instant, and a `package_status` of `ACTIVE`, `SUSPENDED`, or `CANCELLED`. Enrolling a client grants the plan's `included_sessions` as the opening credit balance — recorded as a `CreditLedgerEntry` with reason `GRANT` — sets `current_cycle_end` one cycle out from the current clock, and starts the package `ACTIVE`. "One cycle out" is computed by advancing to the immediately following calendar month (rolling the year forward when advancing past December), landing on the package's `cycle_anchor_day` as the day-of-month while preserving the source instant's time-of-day; the day-of-month of the source instant is otherwise discarded. Every credit movement is journaled to the ledger, and each `CreditLedgerEntry` records the owning `package_id`, the signed `delta_sessions`, a `reason` of `GRANT`, `ROLLOVER_FORFEIT`, `REDEEM`, `REFUND`, or `EXPIRE`, and the `balance_after` — the package's `credit_balance_sessions` immediately after the entry — so that the latest entry's `balance_after` always equals the package's current balance.

A `PracticeAdmin` **renews** an active package once its cycle has ended — renewal is permitted only while `package_status` is `ACTIVE` and only when the clock has reached or passed `current_cycle_end`; an early attempt is rejected with `ERR_RENEWAL_TOO_EARLY`. Renewal applies the rollover cap *before* granting the new cycle, in this pinned order. First the kept amount is the smaller of the current `credit_balance_sessions` and the plan's `rollover_cap_sessions`; the forfeited amount is whatever exceeds that, the current balance minus the kept amount. If anything is forfeited, a `CreditLedgerEntry` with reason `ROLLOVER_FORFEIT` and a negative delta equal to the forfeited count is written. Then the plan's `included_sessions` are granted with a `CreditLedgerEntry` of reason `GRANT`, so the new `credit_balance_sessions` equals the kept amount plus `included_sessions`. Renewal also advances `current_cycle_end` by one cycle. When the balance is at or under the cap, nothing is forfeited and all unused credits roll forward before the grant; when it exceeds the cap, the excess is forfeited (with its `ROLLOVER_FORFEIT` entry) and only the capped amount rolls before the grant.

A package may be **suspended** by a `PracticeAdmin` while `ACTIVE`, freezing its credits without forfeiting them; a suspended package keeps its `credit_balance_sessions` but cannot be redeemed and is skipped by renewal. A suspended package may be **resumed** back to `ACTIVE`. A package may be **cancelled** by a `PracticeAdmin` from either `ACTIVE` or `SUSPENDED`: on cancellation any remaining credits are converted to store credit on the client — a `CreditLedgerEntry` with reason `EXPIRE` zeroes the `credit_balance_sessions`, and the client's `wallet_credit_cents` is increased by the remaining credit count multiplied by the plan's `monthly_fee_cents` divided by its `included_sessions`, rounded half up — after which `package_status` becomes `CANCELLED`. Cancellation bumps both the package's and the client's `version`.

A membership credit is consumed only by a `MEMBERSHIP`-payer session, and only at pricing, governed by the **membership redemption gate**: at price time the payer must be `MEMBERSHIP`, a `package_id` must be supplied, the package must be `ACTIVE`, it must belong to the appointment's client, and its `credit_balance_sessions` must be at least 1. If any of those fail, pricing is rejected with `ERR_NO_CREDITS`; otherwise the redemption writes the `REDEEM` ledger entry described in §3.8.

### 3.11. Insurance Superbills

After a session has been paid out of pocket, the practice can produce an insurance **superbill** for the client to submit to their carrier. A superbill is issued by `FrontDesk` or `PracticeAdmin` against an `appointment_id`, with `diagnosis_codes` (at least one ICD-10 code supporting medical necessity) and a `cpt_code` for the bodywork rendered. The issuing **superbill gate** requires that the appointment's `settlement_status` is `PAID` and that its payer is not `MEMBERSHIP` — membership-redeemed sessions are not insurance-billable — and a request that violates either condition is rejected with `ERR_NOT_BILLABLE`. On issue, the superbill denormalizes the patient's `client_id` from the appointment, sets `billable_amount_cents` equal to the appointment's `service_charge_cents` (gratuity and any membership discount are excluded from the claim), and starts in `superbill_status` `ISSUED`. A superbill may later be voided for claim correction or rebill — permitted only while it is `ISSUED` — which moves `superbill_status` to `VOID`.

## 4. Endpoint Definitions

All endpoints are mounted under the `/practice` prefix (the logical-clock control endpoint excepted). Creating a new resource returns HTTP 201 with the created resource in `data`; reads and state-changing actions that modify an existing resource return HTTP 200 with the affected resource. Errors follow the envelope of §2.2 and the catalogue of §5.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | /practice/modalities | Create a modality | PracticeAdmin |
| GET | /practice/modalities | List modalities (default excludes archived) | PracticeAdmin, FrontDesk, Therapist |
| GET | /practice/modalities/{id} | Fetch a modality | PracticeAdmin, FrontDesk, Therapist |
| POST | /practice/therapists | Create a therapist | PracticeAdmin |
| GET | /practice/therapists | List therapists | PracticeAdmin, FrontDesk |
| GET | /practice/therapists/{id} | Fetch a therapist | PracticeAdmin, FrontDesk, Therapist |
| POST | /practice/therapists/{id}/reset-commission | Reset the therapist's monthly commission accumulators | PracticeAdmin |
| POST | /practice/certifications | Grant a modality certification to a therapist | PracticeAdmin |
| GET | /practice/certifications | List certifications; filter by therapist_id | PracticeAdmin, FrontDesk |
| GET | /practice/certifications/{id} | Fetch a certification | PracticeAdmin, FrontDesk |
| POST | /practice/tables | Create a table/room | PracticeAdmin |
| GET | /practice/tables | List tables (default excludes archived) | PracticeAdmin, FrontDesk |
| GET | /practice/tables/{id} | Fetch a table (includes version for OCC) | PracticeAdmin, FrontDesk |
| POST | /practice/clients | Create a client | PracticeAdmin, FrontDesk |
| GET | /practice/clients | List clients | PracticeAdmin, FrontDesk |
| GET | /practice/clients/{id} | Fetch a client | PracticeAdmin, FrontDesk, Client |
| POST | /practice/clients/{id}/wallet-adjustments | Adjust a client's wallet credit | PracticeAdmin |
| POST | /practice/intakes | Create a DRAFT intake for a client | PracticeAdmin, FrontDesk, Client |
| GET | /practice/intakes | List intakes; filter by client_id | PracticeAdmin, FrontDesk, Client |
| GET | /practice/intakes/{id} | Fetch an intake | PracticeAdmin, FrontDesk, Client |
| POST | /practice/intakes/{id}/sign | Sign a DRAFT intake | Client, FrontDesk |
| POST | /practice/consent-records | Create an ACTIVE consent record | PracticeAdmin, FrontDesk, Client |
| GET | /practice/consent-records | List consent records; filter by client_id | PracticeAdmin, FrontDesk, Client |
| GET | /practice/consent-records/{id} | Fetch a consent record | PracticeAdmin, FrontDesk, Client |
| POST | /practice/consent-records/{id}/revoke | Revoke consent; cascade-cancel referencing appointments | Client, PracticeAdmin |
| POST | /practice/plans | Create a membership plan | PracticeAdmin |
| GET | /practice/plans | List membership plans (default excludes archived) | PracticeAdmin, FrontDesk, Client |
| GET | /practice/plans/{id} | Fetch a plan | PracticeAdmin, FrontDesk, Client |
| POST | /practice/packages | Enroll a client into a plan | PracticeAdmin, FrontDesk |
| GET | /practice/packages | List packages; filter by client_id or plan_id | PracticeAdmin, FrontDesk, Client |
| GET | /practice/packages/{id} | Fetch a package | PracticeAdmin, FrontDesk, Client |
| GET | /practice/packages/{id}/ledger | List a package's credit ledger entries | PracticeAdmin, FrontDesk, Client |
| POST | /practice/packages/{id}/renew | Renew a package: cap then grant | PracticeAdmin |
| POST | /practice/packages/{id}/suspend | Suspend a package | PracticeAdmin |
| POST | /practice/packages/{id}/resume | Resume a suspended package | PracticeAdmin |
| POST | /practice/packages/{id}/cancel-membership | Cancel membership; convert credits to wallet | PracticeAdmin |
| POST | /practice/commission-tiers | Create a global commission tier | PracticeAdmin |
| GET | /practice/commission-tiers | List commission tiers (default excludes archived) | PracticeAdmin, FrontDesk |
| POST | /practice/appointments | Book an appointment | FrontDesk, PracticeAdmin |
| GET | /practice/appointments | List appointments; filter by any FK or status | PracticeAdmin, FrontDesk, Therapist, Client |
| GET | /practice/appointments/{id} | Fetch an appointment | PracticeAdmin, FrontDesk, Therapist, Client |
| POST | /practice/appointments/{id}/check-in | Check in a SCHEDULED appointment | FrontDesk |
| POST | /practice/appointments/{id}/complete | Complete a CHECKED_IN appointment | Therapist, FrontDesk |
| POST | /practice/appointments/{id}/cancel | Cancel an appointment | FrontDesk, PracticeAdmin |
| POST | /practice/appointments/{id}/no-show | Mark an appointment NO_SHOW | FrontDesk, PracticeAdmin |
| POST | /practice/appointments/{id}/waive-no-show | Waive a NO_SHOW | PracticeAdmin |
| POST | /practice/appointments/{id}/price | Price a COMPLETED appointment | FrontDesk, PracticeAdmin |
| POST | /practice/appointments/{id}/pay | Pay a PRICED appointment | FrontDesk, PracticeAdmin |
| POST | /practice/appointments/{id}/void | Void an UNSETTLED/PRICED appointment | PracticeAdmin |
| POST | /practice/soap-notes | Create a DRAFT SOAP note | Therapist |
| GET | /practice/soap-notes | List SOAP notes; filter by appointment_id | PracticeAdmin, Therapist, FrontDesk |
| GET | /practice/soap-notes/{id} | Fetch a SOAP note | PracticeAdmin, Therapist, FrontDesk |
| PATCH | /practice/soap-notes/{id} | Edit a DRAFT SOAP note's S/O/A/P content | Therapist |
| POST | /practice/soap-notes/{id}/finalize | Finalize a DRAFT note (FINALIZED or AMENDED) | Therapist |
| POST | /practice/soap-notes/{id}/reopen | Reopen a FINALIZED note for amendment | Therapist |
| POST | /practice/superbills | Issue an insurance superbill | FrontDesk, PracticeAdmin |
| GET | /practice/superbills | List superbills; filter by appointment_id or client_id | PracticeAdmin, FrontDesk, Client |
| GET | /practice/superbills/{id} | Fetch a superbill | PracticeAdmin, FrontDesk, Client |
| POST | /practice/superbills/{id}/void | Void an ISSUED superbill | FrontDesk, PracticeAdmin |
| POST | /_clock/set_current_utc | Set the server logical clock to an explicit UTC instant | PracticeAdmin |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| --- | --- |
| ERR_UNAUTHENTICATED | 401 |
| ERR_UNAUTHORIZED | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_REQUEST | 422 |
| ERR_INVALID_STATE | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_CONSENT_REQUIRED | 422 |
| ERR_CONTRAINDICATION | 422 |
| ERR_INTAKE_INVALID | 422 |
| ERR_LICENSE_EXPIRED | 422 |
| ERR_CERTIFICATION_REQUIRED | 422 |
| ERR_TABLE_UNSUITABLE | 422 |
| ERR_TABLE_DOUBLE_BOOKED | 409 |
| ERR_THERAPIST_DOUBLE_BOOKED | 409 |
| ERR_NO_CREDITS | 422 |
| ERR_INSUFFICIENT_HSA | 422 |
| ERR_NOT_BILLABLE | 422 |
| ERR_RENEWAL_TOO_EARLY | 422 |
