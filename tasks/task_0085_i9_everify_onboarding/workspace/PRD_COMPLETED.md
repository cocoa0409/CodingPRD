# I-9 & E-Verify Onboarding API — Product Requirements Document

## 1. Introduction

Every employer in the United States must, for each new hire, verify identity and employment eligibility on Form I-9, and many worksites additionally run that hire through the federal E-Verify program. The process is unforgiving: Section 1 must be attested by the employee, Section 2 must be completed by an employer representative within three business days of the first day of work, the documents presented must satisfy a precise "List A or List B plus List C" rule, and any Tentative Nonconfirmation returned by E-Verify must be contested within a tightly bounded referral window or the employment is lost. Noncitizen authorizations expire and must be re-verified, and certain populations — notably F-1 students on Optional Practical Training filing a STEM extension — earn automatic cap-gap extensions that move the reverification deadline.

This API governs that entire lifecycle as a single compliance-and-audit system. It tracks an onboarding from creation through Section 1 attestation, document presentation, Section 2 document review, optional E-Verify adjudication (including TNC contest, referral, and final outcome), reverification via Section 3, and the special STEM-OPT extension path — while latching compliance flags that survive after-the-fact remediation and exposing a forward-looking compliance-risk score. Because the same person may not both complete document review and exercise compliance-officer override authority, the system partitions duties across three operator roles and writes every consequential action to an append-only audit log. Deadlines are evaluated against a deterministic, test-drivable server clock so that the time-crossing transitions (a lapsed authorization, an unreferred TNC, an unmet reverification) can be exercised reproducibly.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, contracts, and conventions that apply across every endpoint. The structural rules here (the response envelope, pagination, common properties, precision, concurrency) are precise contracts; deviating from them breaks interoperability.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity under which they act. The system recognizes exactly three roles, spelled precisely: `HRReviewer`, `EVerifyOperator`, and `ComplianceOfficer`. On any mutating endpoint, a request that omits either header, or whose `X-User-Role` is not one of these three known roles, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). Read endpoints (the `GET` operations) are permissive: any of the three known roles may read. When a role is authenticated but is not permitted to perform the requested operation under the access matrix described throughout §3 and tabulated in §4, the request is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403).

All three roles carry an **opaque** identity. When `X-User-Role` is `HRReviewer`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server records it where a workflow demands it — for example as `section2_reviewer_id` on the `I9Form` when that reviewer completes Section 2, or as `reviewer_id` on a `ReverificationEvent` when that reviewer records a Section 3 block — but it never compares it to any entity's `id`. When `X-User-Role` is `EVerifyOperator`, `X-User-ID` is likewise an opaque operator identifier not tied to any persisted entity; the server may record it (for instance as `actor_user_id` on an `AuditEntry`) but does not compare it to any entity's `id`. When `X-User-Role` is `ComplianceOfficer`, `X-User-ID` is again an opaque operator identifier not tied to any persisted entity, recorded on audit entries but never matched against an entity's `id`.

One identity comparison does exist, and it is between two operator identifiers rather than between an identifier and an entity `id`: **segregation of duties** on the compliance override. The `ComplianceOfficer` who applies an override on an onboarding must not be the same `X-User-ID` that completed Section 2 on that onboarding's `I9Form` (the value captured in `section2_reviewer_id`). A violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403). This is the structural reason the override authority is partitioned away from the document-review authority.

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` parameter sets the maximum number of items returned; it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset` parameter sets the number of items to skip and defaults to 0. A `limit` or `offset` outside these bounds is rejected with `ERR_VALIDATION_PAGINATION` (HTTP 400).

Unless otherwise specified, all list endpoints return resources sorted by their creation timestamp (`created_at`) in ascending order. Every paginated list response includes `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

The principal resources — `Onboarding`, `I9Form`, `IdentityDocument`, `EVerifyCase`, `WorkAuthorization`, and `ReverificationEvent` — share a standard set of system-managed fields:

- **`id`** — a unique, server-minted identifier formatted as a UUID with no type prefix.
- **`created_at`** — an ISO 8601 UTC timestamp with three fractional digits recording when the resource was first created.
- **`updated_at`** — an ISO 8601 UTC timestamp recording the most recent modification; it is refreshed on every mutation of the resource.
- **`version`** — a system-managed integer that begins at creation and increments by one on every mutation. It underpins the optimistic concurrency control described in §2.7.

The `AuditEntry` resource is the one exception: it is an append-only event-log record that carries only `id` and `created_at`. An `AuditEntry` has no `updated_at` and no `version`, because it is never modified after it is written.

Every entity that references another does so through an identifier field rather than an embedded object. These foreign-key fields — for example `onboarding_id`, `i9_form_id`, `work_authorization_id`, and the self-referential `supersedes_id` — are plain UUID strings.

### 2.5. Nested Path Resolution and Reverse Reachability

The system uses a flat collection topology: onboardings, I-9 forms, identity documents, E-Verify cases, work authorizations, reverification events, and audit entries are all top-level collections joined by foreign-key references rather than nested under one another. When an endpoint path or request body names one or more resources, the system validates their existence left to right, in the order they appear, and rejects the request with `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to an existing resource. For example, recording a Section 3 block names both the form in the path and a `work_authorization_id` in the body; the form is checked first, then the work authorization.

Because relationships are expressed by foreign keys, child collections are reachable in reverse from the parent. Identity documents, I-9 forms, E-Verify cases, work authorizations, reverification events, and audit entries can each be filtered by their owning `onboarding_id` (or, where applicable, by `i9_form_id`, `work_authorization_id`, or `supersedes_id`) so that a caller holding only a parent's `id` can enumerate everything that points back to it. Several list endpoints also accept a `status` query parameter that restricts results to resources whose `status` field equals the supplied value — onboardings, identity documents, E-Verify cases, and work authorizations all support this filter. Section 3 blocks recorded on a particular form are additionally listable directly from that form.

### 2.6. Precision, Clocks, and Deadline Arithmetic

This domain is dominated by dates and deadlines rather than money. All timestamps are ISO 8601 in UTC. The server runs against a **deterministic logical clock**: rather than reading wall-clock time, deadline-crossing transitions are evaluated against a clock value that a `ComplianceOfficer` may set explicitly (see §3.7). Wherever this document says "the clock," it means that server clock.

Business-day arithmetic underlies the two principal deadlines. A "business day" excludes Saturdays and Sundays and the fixed federal-holiday set for 2026: January 1, January 19, February 16, May 25, June 19, July 3, September 7, November 11, November 26, and December 25. Counting begins the first business day *after* the anchor date — that anchor day itself is never counted as day one. Whole-day arithmetic is performed in UTC, and a deadline is stamped at 23:59:59.999Z of the resolved day. The compliance-risk score described in §3.6 is the only numeric calculation; it is summed first and then rounded once, half up, with per-term rounding forbidden, and the result is clamped into the range 0 through 100 inclusive.

### 2.7. Optimistic Concurrency Control on Onboarding Mutations

Two write operations require the caller to prove it is acting on a current view of the onboarding, because each can be invalidated by a competing write that advanced the onboarding's lifecycle. Both pass the onboarding's last-observed `version` in a non-optional body field named `expected_onboarding_version`, and both compare it against the onboarding's current `version`; a mismatch is rejected with `ERR_STALE_ONBOARDING_VERSION` (HTTP 412).

The first is **completing Section 2**: the request must carry `expected_onboarding_version` equal to the target onboarding's current `version`. If another reviewer has already completed Section 2 — legitimately accepting a documentary set and superseding the other presented documents — the onboarding's `version` will have advanced past what the current reviewer last read, so their view of which documents are still `PRESENTED` is stale, and the completion is rejected with `ERR_STALE_ONBOARDING_VERSION` (HTTP 412).

The second is **submitting an E-Verify case**: the create request must carry `expected_onboarding_version` equal to the backing onboarding's current `version`. If the onboarding has already advanced past `SECTION2_COMPLETE` — for instance because a competing operator's submission drove it to `EVERIFY_PENDING` and bumped its `version` — the stale value no longer matches and the create is rejected with `ERR_STALE_ONBOARDING_VERSION` (HTTP 412). No other endpoint takes a version field; only these two carry `expected_onboarding_version`.

### 2.8. Validation Ordering

When several checks guard one endpoint, they are evaluated in a fixed priority order so that the returned error is deterministic. The global order, highest priority first, is: authentication of the request headers (`ERR_UNAUTHENTICATED`, 401); role permission for the operation (`ERR_FORBIDDEN_ROLE`, 403); segregation of duties on an override (`ERR_SEGREGATION_OF_DUTIES`, 403); existence of every referenced resource, checked left to right (`ERR_NOT_FOUND`, 404); the target resource being in a state from which the requested transition is defined (`ERR_INVALID_STATE`, 409); the no-duplicate-E-Verify-case guard (`ERR_EVERIFY_CASE_EXISTS`, 409); document ownership on Section 2 (`ERR_DOCUMENT_NOT_OWNED`, 422); Section 1 completeness for an authorized-alien attestation (`ERR_SECTION1_INCOMPLETE`, 422); the documentary-combination rule (`ERR_DOCUMENT_COMBINATION_INVALID`, 422); document/authorization expiry (`ERR_DOCUMENT_EXPIRED`, 422); the STEM filing window (`ERR_STEM_WINDOW_MISSED`, 422); the TNC referral window (`ERR_REFERRAL_WINDOW_CLOSED`, 422); the late-reason requirement (`ERR_LATE_REASON_REQUIRED`, 422); the onboarding-version concurrency check (`ERR_STALE_ONBOARDING_VERSION`, 412); and finally generic body well-formedness and enum-domain validation (`ERR_INVALID_REQUEST`, 400). A check that ranks earlier is decided before any later check runs, so an unauthenticated caller never learns about a state problem, and a wrong-role caller never learns about a document problem.

### 2.9. State Propagation and the Audit Trail

State lives at two levels and they move together. The `I9Form` carries a form-level lifecycle independent of the E-Verify outcome, while the `Onboarding` carries the aggregate lifecycle that E-Verify and reverification feed back into. When an operation completes, it both advances the directly targeted resource and applies any cascade onto the related resources, in the same transaction; each affected resource that changes has its `updated_at` refreshed, and each onboarding mutation increments `Onboarding.version` by one. The detailed cascades — Section 2 superseding unchosen documents, an E-Verify result driving the onboarding to `AUTHORIZED` or `TERMINATED_NONCONFIRMED`, a reverification superseding the prior authorization — are described in §3 with their preconditions.

Every consequential action also appends an `AuditEntry`. Each entry records the `onboarding_id` it targeted, the `actor_role` (`HRReviewer`, `ComplianceOfficer`, `EVerifyOperator`, or `system` for automatic transitions), the `actor_user_id` (the acting `X-User-ID`, or the literal `system` for automatic transitions), the `action` (a code such as `SECTION2_COMPLETED`, `EVERIFY_SUBMITTED`, `TNC_REFERRED`, `REVERIFIED`, or `OVERRIDE_APPLIED`), and a human-readable `detail` summarizing what changed. The audit log is append-only and is never edited.

## 3. Business Logic & Workflows

### 3.1. Creating an Onboarding and Attesting Section 1

An onboarding is opened by an `HRReviewer` or a `ComplianceOfficer`. The creation payload supplies the new hire's legal name in `employee_full_name`, contact address in `employee_email`, the Section 1 attested `citizenship_status`, and the `hire_date` — the first day of employment for pay, which anchors the I-9 clock. The `citizenship_status` is one of `US_CITIZEN`, `NONCITIZEN_NATIONAL`, `LPR`, or `ALIEN_AUTHORIZED`. When and only when the status is `ALIEN_AUTHORIZED`, the payload must also supply `work_auth_expiration`, the self-attested expiration of employment authorization from Section 1; for citizens, nationals, and lawful permanent residents this field is null. The payload may also set `requires_everify`, which declares whether the worksite is enrolled in E-Verify and gates whether an E-Verify case is ever created; it defaults to true when omitted.

At creation the onboarding enters `CREATED` status, the system pins its Section 2 deadline into `section2_deadline` from the `hire_date` (see §3.2 for the arithmetic), and a backing `I9Form` is created in `SECTION1_PENDING` carrying this onboarding's `onboarding_id`. The compliance flag `is_overdue` starts false. The form tracks Section 1 work through `section1_attested_at` (the server timestamp of attestation, null until then), the boolean `section1_preparer_used` (whether a preparer or translator assisted, defaulting to false), and a `current_section3_count` that starts at 0.

Section 1 attestation is performed by an `HRReviewer` and is the transition that takes the onboarding from `CREATED` to `SECTION1_COMPLETE`. It is permitted only when the onboarding is currently in `CREATED`; otherwise it is rejected with `ERR_INVALID_STATE`. The attestation request may carry `section1_preparer_used`. Before Section 1 may complete, the system enforces that an `ALIEN_AUTHORIZED` attestation carries a present, well-formed `work_auth_expiration`; if it is missing, the attestation is rejected with `ERR_SECTION1_INCOMPLETE`. On success the system stamps `section1_attested_at` to the clock, advances the form from `SECTION1_PENDING` to `SECTION1_DONE`, moves the onboarding to `SECTION1_COMPLETE`, and increments the onboarding's `version` by one. We record the attestation; we do not enforce that it landed by the first day of employment.

### 3.2. The Three-Business-Day Section 2 Deadline and the Overdue Flag

The Section 2 completion deadline is computed once, at onboarding creation, and pinned onto `section2_deadline`. Starting from the calendar date of `hire_date` taken at 00:00:00Z, the system walks forward one calendar day at a time; each day that is neither a Saturday nor a Sunday nor one of the 2026 federal holidays counts as one business day, and the walk stops once three business days have been counted. The first business day strictly after `hire_date` is day one — the hire date itself never counts. The third counted business day, stamped at 23:59:59.999Z, is the `section2_deadline`.

The `is_overdue` flag is a latching compliance signal, distinct from the state machine. It becomes true in either of two situations: when Section 2 has not yet been completed (`section2_completed_at` is still null) and the clock has moved strictly past `section2_deadline`; or when Section 2 was completed but its `section2_completed_at` falls strictly after `section2_deadline`. Once `is_overdue` is true it stays true — reaching `SECTION2_COMPLETE`, even late, does not clear it. The only thing that clears it is a `ComplianceOfficer` override (see §3.5). Lateness is recorded, never blocked: Section 2 may still be completed after the deadline, mirroring real enforcement practice.

### 3.3. Presenting Documents and Completing Section 2

Before Section 2 can be completed, the employee's documents are presented one at a time by an `HRReviewer`. Each presentation supplies the owning `onboarding_id`, the `list_category` (`LIST_A`, `LIST_B`, or `LIST_C`), a `document_title` such as `US_PASSPORT`, `PERMANENT_RESIDENT_CARD`, `EAD`, `DRIVERS_LICENSE`, `SS_CARD`, or `FORM_I20`, and the `document_number` as presented. An `expiration_date` may be supplied; a null `expiration_date` means the document does not expire (a List C Social Security card or a List B school identification may be unexpiring). The boolean `is_receipt` (default false) marks a document presented as a receipt for a lost, stolen, or replacement document, which triggers the 90-day receipt rule described below. A presented document begins in `PRESENTED` status, with `accepted_for_section2` false and `receipt_resolution_deadline` null until Section 2 resolves it.

Completing Section 2 is an `HRReviewer` action that moves the onboarding from `SECTION1_COMPLETE` to `SECTION2_COMPLETE`. The request body names the chosen documents in `document_ids` and carries `expected_onboarding_version` for the concurrency check of §2.7. The transition runs a sequence of guards. First, the onboarding must be in `SECTION1_COMPLETE`, or it is rejected with `ERR_INVALID_STATE`. Every chosen document named in `document_ids` must belong to the onboarding in the path; a chosen document that points at a different `onboarding_id` is rejected with `ERR_DOCUMENT_NOT_OWNED`. Each chosen document must currently be in `PRESENTED` status; a chosen document that is no longer `PRESENTED` (for example one already `ACCEPTED` or `SUPERSEDED`) is rejected with `ERR_DOCUMENT_COMBINATION_INVALID`.

The chosen set must then satisfy **exactly one** documentary path. The system partitions the chosen documents by `list_category`. The set is sufficient when either exactly one List A document is chosen and no List B and no List C document is chosen — in which case the single List A document proves both identity and work authorization and the form's `chosen_document_path` is recorded as `LIST_A` — or exactly one List B document and exactly one List C document are chosen and no List A document is chosen, in which case the List B document proves identity, the List C document proves work authorization, and `chosen_document_path` is recorded as `LIST_B_AND_C`. Any other cardinality — zero documents, two List A documents, a lone List B, a List B with two List C documents, and so on — is rejected with `ERR_DOCUMENT_COMBINATION_INVALID`; there is no partial credit. Until Section 2 completes, `chosen_document_path` reads `UNSET`.

Each chosen document that is not a receipt must be unexpired as of the clock: a document with a non-null `expiration_date` is valid only when that expiration is strictly after the clock. A document expiring exactly at the clock value is treated as expired. A non-receipt chosen document that is expired by this rule is rejected with `ERR_DOCUMENT_EXPIRED`. Receipts are exempt from the expiry check at acceptance because they stand in for an expired or lost document; a document whose `expiration_date` is null (non-expiring) is likewise always valid.

On success, the system marks each chosen document `accepted_for_section2` true and moves it from `PRESENTED` to `ACCEPTED`, and every other still-`PRESENTED` document for this onboarding is set to `SUPERSEDED`. For any accepted document that is a receipt, the system computes `receipt_resolution_deadline` as `section2_completed_at` plus 90 calendar days — the date by which the actual document must replace the receipt. The form records the `chosen_document_path`, stamps `section2_reviewer_id` to the acting `X-User-ID` and `section2_completed_at` to the clock, and advances from `SECTION1_DONE` to `SECTION2_DONE`. An `AuditEntry` with action `SECTION2_COMPLETED` is appended, the onboarding moves to `SECTION2_COMPLETE`, and its `version` increments by one. Section 2 may complete after `section2_deadline`; doing so latches `is_overdue` per §3.2 but is not itself blocked.

### 3.4. E-Verify Submission and Adjudication

For a worksite enrolled in E-Verify, an `EVerifyOperator` submits a case once Section 2 is complete. The submission supplies the `onboarding_id`, the backing `i9_form_id` (the completed Section 2 form), and `expected_onboarding_version` for the concurrency check; it may also carry a `late_reason`. The case may be created when the backing onboarding is in `SECTION2_COMPLETE` (the state machine also tolerates an onboarding already in `EVERIFY_PENDING` only so that the duplicate-case guard, rather than the state guard, is what rejects a second attempt). A submission is refused with `ERR_EVERIFY_CASE_EXISTS` when any other non-terminal case — one whose status is not `EMPLOYMENT_AUTHORIZED` and not `FINAL_NONCONFIRMATION` — already exists for this onboarding; this duplicate guard additionally catches a second create while the onboarding is still in `SECTION2_COMPLETE`.

A case is minted directly in `SUBMITTED` (its `DRAFT` status is only a pre-create logical placeholder). The submission stamps `submitted_at` to the clock and computes `everify_deadline`, which equals the backing onboarding's `section2_deadline` — that is, three business days after `hire_date` by the identical weekend-and-federal-holiday arithmetic of §3.2. The case is `was_late` exactly when `submitted_at` is strictly after `everify_deadline`. A late submission must carry a non-empty `late_reason`; a late case without one is rejected with `ERR_LATE_REASON_REQUIRED`. Submitting the case drives the onboarding from `SECTION2_COMPLETE` to `EVERIFY_PENDING`, appends an `AuditEntry` with action `EVERIFY_SUBMITTED`, and increments the onboarding's `version` by one. A fresh case starts with `tnc_type` of `NONE`, `tnc_issued_at` null, and `referral_deadline` null.

Adjudication results are recorded by an `EVerifyOperator` against a case. The `result` carried in the request is one of `AUTHORIZED`, `TNC`, `NO_ACTION`, or `FINAL_NONCONFIRMATION`; a `TNC` result also names the issuing `agency` (`SSA` or `DHS`). From `SUBMITTED`, an `AUTHORIZED` result moves the case to `EMPLOYMENT_AUTHORIZED` and cascades the onboarding from `EVERIFY_PENDING` to `AUTHORIZED`, appending an `AuditEntry` with action `AUTHORIZED`. From `SUBMITTED`, a `TNC` result moves the case to `TNC_ISSUED`: the system sets `tnc_type` to `SSA_TNC` or `DHS_TNC` according to the agency, stamps `tnc_issued_at` to the clock, and computes `referral_deadline` as `tnc_issued_at` plus 10 federal-government business days; an `AuditEntry` with action `TNC_ISSUED` is appended, and the onboarding stays in `EVERIFY_PENDING` throughout TNC handling. A result recorded against a case not in the required state is rejected with `ERR_INVALID_STATE`.

The employee's contest of a Tentative Nonconfirmation is recorded as a referral by an `EVerifyOperator`, moving the case from `TNC_ISSUED` to `REFERRED`. A referral is timely only when the clock is at or before `referral_deadline`; a referral attempted after that deadline has passed is rejected with `ERR_REFERRAL_WINDOW_CLOSED`. From `REFERRED`, a subsequent `AUTHORIZED` result moves the case to `EMPLOYMENT_AUTHORIZED` and cascades the onboarding from `EVERIFY_PENDING` to `AUTHORIZED`, appending an `AuditEntry` with action `AUTHORIZED_AFTER_REFERRAL`; a `FINAL_NONCONFIRMATION` result from `REFERRED` moves the case to `FINAL_NONCONFIRMATION` and cascades the onboarding from `EVERIFY_PENDING` to `TERMINATED_NONCONFIRMED`, appending an `AuditEntry` with action `FINAL_NONCONFIRMATION`. From `TNC_ISSUED`, the case reaches `FINAL_NONCONFIRMATION` either by an explicit `NO_ACTION` close or automatically when the clock crosses `referral_deadline` with no referral on record; in both cases the onboarding cascades from `EVERIFY_PENDING` to `TERMINATED_NONCONFIRMED` and an `AuditEntry` with action `FINAL_NONCONFIRMATION` is appended. When a system-driven case reaches `EMPLOYMENT_AUTHORIZED`, the onboarding's move to `AUTHORIZED` is audited with action `AUTHORIZED`; when it reaches `FINAL_NONCONFIRMATION`, the onboarding's move to `TERMINATED_NONCONFIRMED` is audited with action `TERMINATED_NONCONFIRMED`.

### 3.5. Finalization and Compliance Override

An onboarding at a worksite **not** enrolled in E-Verify never opens a case. Instead, once Section 2 is complete, a `ComplianceOfficer` finalizes it directly: when `requires_everify` is false and the onboarding is in `SECTION2_COMPLETE`, finalization moves it to `AUTHORIZED`, appends an `AuditEntry` with action `AUTHORIZED_NO_EVERIFY`, and increments the onboarding's `version` by one. Finalization from any other state is rejected with `ERR_INVALID_STATE`.

The **compliance override** is the `ComplianceOfficer`'s remediation lever. It carries an `override_reason` and force-clears the latched compliance posture — setting `is_overdue` back to false and accepting a late posture under a recorded justification — then appends an `AuditEntry` with action `OVERRIDE_APPLIED` and increments the onboarding's `version` by one. The override is the only mechanism that clears `is_overdue`. It is subject to segregation of duties: the `X-User-ID` applying the override must differ from the `section2_reviewer_id` recorded on the onboarding's form, or the request is rejected with `ERR_SEGREGATION_OF_DUTIES`, as detailed in §2.1.

### 3.6. Work Authorizations, STEM Extensions, and Reverification

Noncitizen work eligibility is tracked as one or more `WorkAuthorization` records created by an `HRReviewer`. Each carries the owning `onboarding_id`, an `auth_type` (`EAD`, `F1_OPT`, `F1_STEM_OPT`, `TPS`, or `OTHER`), and an authorization interval given by `valid_from` (inclusive start) and `valid_until` (inclusive last authorized day). The boolean `stem_extension_applied` (default false) marks the record as a STEM OPT extension filed against an F-1 OPT base period, and `supersedes_id` references the prior authorization being extended or replaced (null for a base record). A base record carries `cap_gap_days` of 0 and an `effective_valid_until` equal to its `valid_until`, and starts `ACTIVE`.

A **STEM OPT extension** is filed by presenting a new authorization with `stem_extension_applied` true and `supersedes_id` pointing at the base, optionally carrying `requested_gap_days` for the auto-extension. It is timely only when the base authorization it supersedes is of `auth_type` `F1_OPT` and is currently `ACTIVE`, and when the extension is filed (its creation clock) on or before the base's `valid_until` — the comparison is inclusive, so filing exactly on the base `valid_until` is still timely. If the base is not an `F1_OPT` record, if it is not currently `ACTIVE`, if `supersedes_id` is omitted so there is no base to extend, or if the filing clock is strictly after the base `valid_until`, the extension is rejected with `ERR_STEM_WINDOW_MISSED`. When timely, the system grants a cap-gap auto-extension while the application is pending: `cap_gap_days` is the requested number of days but capped at a ceiling of 180, so a request of 180 or fewer days grants exactly that many while a request exceeding 180 clamps to 180. An omitted `requested_gap_days` is treated as 0, and a negative request is floored to 0, so `cap_gap_days` is never below 0. The new record's `effective_valid_until` is its base `valid_until` plus `cap_gap_days` days — the date by which reverification must occur under the active extension. Filing the extension moves the superseded base from `ACTIVE` to `EXTENDED` and the new extension record is itself `ACTIVE` or `EXTENDED`.

Once an onboarding is `AUTHORIZED`, the system watches the controlling authorization's `effective_valid_until`. When the clock crosses that date — and no later recorded Section 3 block already covers it — the onboarding automatically moves from `AUTHORIZED` to `REVERIFICATION_DUE` (audited with action `REVERIFICATION_DUE`, onboarding `version` bumped). If a base authorization's `effective_valid_until` is crossed with neither a STEM extension nor a reverification recorded, that authorization itself moves from `ACTIVE` to `EXPIRED`.

**Reverification (Section 3)** is recorded by an `HRReviewer` against a form, moving the onboarding from `REVERIFICATION_DUE` back to `AUTHORIZED`. The request names the new `work_authorization_id` presented at reverification, the `reverification_reason` (`EXPIRING_AUTH`, `REHIRE`, or `NAME_CHANGE`), and the `new_expiration_date` of the document presented. The transition is permitted only when the onboarding is in `REVERIFICATION_DUE`, or it is rejected with `ERR_INVALID_STATE`; the presented authorization must itself be valid — its `effective_valid_until` strictly after the clock, by the same strict-after rule that governs document expiry — and a presented authorization that is already expired is rejected with `ERR_DOCUMENT_EXPIRED`. On success the system creates a `ReverificationEvent` in `RECORDED` status capturing the form's `i9_form_id`, the `work_authorization_id`, the `reverification_reason`, the `new_expiration_date`, the acting `reviewer_id`, and a `completed_at` server timestamp; Section 3 blocks are append-only and always `RECORDED`. The form's `current_section3_count` increments and its status advances to `REVERIFIED`, the prior `WorkAuthorization` is marked `SUPERSEDED` while the newly presented one is `ACTIVE` or `EXTENDED`, an `AuditEntry` with action `REVERIFIED` is appended, and the onboarding's `version` increments by one. The "prior `WorkAuthorization`" here is the controlling authorization being replaced — the non-`SUPERSEDED` record on this onboarding with the latest `effective_valid_until`, considered to the exclusion of the just-presented `work_authorization_id` so the new record is never mistaken for the prior — and it is marked `SUPERSEDED` whether it is currently `ACTIVE`, `EXTENDED`, or already `EXPIRED` (the last when a clock-driven advance into `REVERIFICATION_DUE` already lapsed it from `ACTIVE`/`EXTENDED` to `EXPIRED`). If, by contrast, the clock moves past the controlling authorization's `effective_valid_until` while the onboarding sits in `REVERIFICATION_DUE` and no covering Section 3 block is recorded, the onboarding moves automatically to the terminal `EXPIRED_UNAUTHORIZED` (audited with action `EXPIRED_UNAUTHORIZED`, `version` bumped).

### 3.7. Driving the Clock and Applying Due Transitions

Because every deadline is evaluated against the deterministic server clock, a `ComplianceOfficer` holds a test-driving capability that sets the current UTC instant from a supplied `to_iso8601` value; the response `data` echoes the newly set instant as `{ "current_utc": <iso8601 timestamp> }` rather than a persisted entity, and subsequent lifecycle evaluations measure their deadlines against that clock. Advancing the clock does not by itself mutate onboardings.

To realize the clock-driven automatic transitions, a `ComplianceOfficer` or an `EVerifyOperator` invokes a per-onboarding lifecycle-advance capability. It re-derives the onboarding's, its work authorizations', and its E-Verify case's deadlines against the current clock and applies whichever automatic transitions are now due — the move into `REVERIFICATION_DUE` when a controlling `effective_valid_until` has been crossed, the move into `EXPIRED_UNAUTHORIZED` when a reverification was never recorded, and the move of a `TNC_ISSUED` case (and its onboarding) into `FINAL_NONCONFIRMATION` when `referral_deadline` has lapsed. When any such transition fires, the onboarding's `version` increments by one.

### 3.8. The Compliance-Risk Score

A read-only compliance-risk summary is available for any onboarding and is recomputed after every onboarding-affecting mutation. It returns three values: an integer `risk_score`, the boolean `is_overdue` flag, and an `open_tnc` boolean indicating whether the case carries an unresolved Tentative Nonconfirmation — true exactly when the onboarding's E-Verify case has a `tnc_type` other than `NONE` and the onboarding has not reached `AUTHORIZED`, and false when there is no case. The `risk_score` is a forward-looking exposure score on the onboarding domain, distinct from per-document validity, assembled as a weighted sum and then rounded once and clamped.

Starting from zero, the score accumulates: 40 points when `is_overdue` is true; 25 points when the onboarding's E-Verify case is `was_late`; 20 points when the case's `tnc_type` is something other than `NONE` and the onboarding has not reached `AUTHORIZED`; 15 points for each accepted identity document that is a receipt (`is_receipt` true, status `ACCEPTED`) whose `receipt_resolution_deadline` is earlier than the clock; and 10 points if any of the onboarding's non-`SUPERSEDED` `WorkAuthorization` records has an `effective_valid_until` within 30 days of the clock — meaning its `effective_valid_until` lies in the inclusive window from the clock through the clock plus 30 calendar days, so an authorization whose `effective_valid_until` already falls strictly before the clock does not contribute this term (zero otherwise). The accumulated total is summed first, then rounded half up, then clamped so that the final `risk_score` never exceeds 100 (and is never below 0); per-term rounding is not performed.

## 4. Endpoint Definitions

Creating a new, stand-alone resource (an onboarding, an identity document, a work authorization, an E-Verify case, or a Section 3 reverification block) returns `201 Created`. Operations that modify an existing resource — attesting, completing, finalizing, overriding, advancing, recording results, referring, and setting the clock — return `200 OK`. Reads return `200 OK`. The request and response payloads for each operation are described in the §3 narratives, not in this table.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/onboardings` | Create a new onboarding (employee record + Section 1 inputs) | HRReviewer, ComplianceOfficer |
| GET | `/onboardings` | List onboardings with pagination and optional status filter | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/onboardings/{id}` | Retrieve a single onboarding | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/onboardings/{id}/risk` | Computed compliance-risk summary for an onboarding | HRReviewer, ComplianceOfficer, EVerifyOperator |
| POST | `/onboardings/{id}/section1-attest` | Record the Section 1 employee attestation | HRReviewer |
| POST | `/onboardings/{id}/section2-complete` | Complete Section 2 by accepting a sufficient documentary set | HRReviewer |
| POST | `/onboardings/{id}/finalize` | Finalize a non-E-Verify onboarding directly to AUTHORIZED | ComplianceOfficer |
| POST | `/onboardings/{id}/override` | ComplianceOfficer override: clear is_overdue / accept a late posture with justification | ComplianceOfficer |
| POST | `/onboardings/{id}/advance-lifecycle` | Re-derive deadlines and apply due automatic transitions for one onboarding | ComplianceOfficer, EVerifyOperator |
| POST | `/identity-documents` | Present an identity document against an onboarding | HRReviewer |
| GET | `/identity-documents` | List/filter identity documents | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/identity-documents/{id}` | Retrieve a single identity document | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/i9-forms` | List/filter I-9 forms | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/i9-forms/{id}` | Retrieve a single I-9 form | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/i9-forms/{id}/section3` | List Section 3 reverification events on a form | HRReviewer, ComplianceOfficer, EVerifyOperator |
| POST | `/i9-forms/{id}/section3` | Record a Section 3 reverification/rehire block against a new work authorization | HRReviewer |
| GET | `/reverification-events` | List/filter Section 3 reverification events | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/reverification-events/{id}` | Retrieve a single Section 3 reverification event | HRReviewer, ComplianceOfficer, EVerifyOperator |
| POST | `/everify-cases` | Submit an E-Verify case for a Section-2-complete onboarding | EVerifyOperator |
| GET | `/everify-cases` | List/filter E-Verify cases | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/everify-cases/{id}` | Retrieve a single E-Verify case | HRReviewer, ComplianceOfficer, EVerifyOperator |
| POST | `/everify-cases/{id}/result` | Record an E-Verify adjudication result | EVerifyOperator |
| POST | `/everify-cases/{id}/refer` | Record the employee's referral/contest of a TNC within the window | EVerifyOperator |
| POST | `/work-authorizations` | Record a work authorization (base, EAD, F-1 OPT, STEM extension, TPS) | HRReviewer |
| GET | `/work-authorizations` | List/filter work authorizations | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/work-authorizations/{id}` | Retrieve a single work authorization | HRReviewer, ComplianceOfficer, EVerifyOperator |
| GET | `/audit-entries` | List/filter the append-only audit log | ComplianceOfficer, EVerifyOperator, HRReviewer |
| GET | `/audit-entries/{id}` | Retrieve a single append-only audit log entry | ComplianceOfficer, EVerifyOperator, HRReviewer |
| POST | `/_clock/set_current_utc` | Test-driving: set the deterministic server clock | ComplianceOfficer |

## 5. Error Code Catalogue

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_UNAUTHENTICATED` | 401 |
| `ERR_FORBIDDEN_ROLE` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_EVERIFY_CASE_EXISTS` | 409 |
| `ERR_DOCUMENT_NOT_OWNED` | 422 |
| `ERR_SECTION1_INCOMPLETE` | 422 |
| `ERR_DOCUMENT_COMBINATION_INVALID` | 422 |
| `ERR_DOCUMENT_EXPIRED` | 422 |
| `ERR_STEM_WINDOW_MISSED` | 422 |
| `ERR_REFERRAL_WINDOW_CLOSED` | 422 |
| `ERR_LATE_REASON_REQUIRED` | 422 |
| `ERR_STALE_ONBOARDING_VERSION` | 412 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VALIDATION_PAGINATION` | 400 |
