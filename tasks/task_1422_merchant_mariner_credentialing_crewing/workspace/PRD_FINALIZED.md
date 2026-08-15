# Merchant Mariner Crewing API — Product Requirements Document

## 1. Introduction

A vessel crewing department lives at the intersection of federal credentialing, union dispatch rules, and the hard arithmetic of safe manning. Credentials lapse, medical certificates expire, drug-test currency windows close, and every one of those clocks can invalidate a crewing decision that was sound the day before it sailed. This document specifies the Merchant Mariner Crewing API: a system that maintains each mariner's credential and endorsement inventory with expiration tracking, documents sea service and evaluates upgrade eligibility, administers medical certificates and drug-test program participation, and manages crew rotation, relief scheduling, travel and repatriation logistics, and training course booking with reimbursement.

On the vessel side, the API models the safe manning document as a set of billets, derives a live compliance posture from actual on-board coverage, gates departure on that posture, and plans rotations and reliefs around bounded handover windows. Two sourcing channels — direct hire and union hall dispatch — carry distinct actor rules, dues-currency checks, and reimbursement economics, and segregation-of-duties constraints keep the officer who records sea service from verifying it and the manager who approves training from paying it out. A logical, admin-controlled clock drives deterministic expiry sweeps so that every time-based rule in this document can be exercised end to end.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, principles, and boilerplate that apply to the entire API.

### 2.1. User and Role-Based Access Control

Every request must carry two HTTP headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the operational capacity in which they act. A request missing either header, or carrying an empty value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). The system recognizes exactly six roles, spelled precisely as follows: `FleetAdmin`, `CredentialingOfficer`, `CrewingManager`, `PortCaptain`, `UnionDispatcher`, and `Mariner`. When the supplied role is not among the roles authorized for the target endpoint, the request is rejected with `ERR_UNAUTHORIZED_ROLE` (HTTP 403).

The meaning of `X-User-ID` depends on the role. When `X-User-Role` is `FleetAdmin`, `CredentialingOfficer`, `CrewingManager`, or `PortCaptain`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `entered_by_user_id` on a sea-service record or `approved_by_user_id` on an enrollment) but never compares it to any entity's `id`. When `X-User-Role` is `Mariner`, `X-User-ID` is the `id` of the acting Mariner record; ownership checks on any resource that references a mariner compare the resource's mariner foreign-key field to `X-User-ID`. When `X-User-Role` is `UnionDispatcher`, `X-User-ID` is the `id` of the acting UnionHall; hall-scoped checks compare the hall identifier in the path, or the hall referenced by a union registration, to `X-User-ID`.

Two resource-scoping rules follow from these identities. A caller with role `Mariner` may only address their own mariner id — their own `/mariners/{id}` subtree and resources linked to it — and a caller with role `UnionDispatcher` may only mutate registrations of their own hall (the hall id in the path must equal `X-User-ID`) and may only act on union-dispatch assignments whose union registration belongs to their own hall. Either violation is rejected with `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403).

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

List endpoints are paginated through two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10, accepts a minimum of 1, and accepts a maximum of 100. The `offset` parameter skips a number of items from the front of the result set and defaults to 0. Unless a more specific rule is stated, every list endpoint returns its resources sorted by `created_at` in ascending order. Paginated list responses carry `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the envelope.

### 2.4. Common Resource Properties

Every resource in this system — mariners, vessels, manning slots, rotation plans, credentials, sea-service records, medical certificates, drug tests, courses, enrollments, training budgets, union halls, registrations, assignments, and travel bookings — carries the same four system-managed properties:

- `id` (string): a unique, server-minted identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording the last modification.
- `version` (integer): a system-managed integer that increments by 1 with every modification of the resource.

Any change to a resource's persisted fields counts as a mutation — including recomputation of derived fields such as a vessel's `compliance_posture` or a mariner's `readiness_posture`, and including changes applied by system cascades — and therefore refreshes `updated_at` and increments `version`. No entity in this system is exempt: there are no resources without `updated_at` and `version`.

### 2.5. Request Validation Pipeline and Nested Resource Retrieval

Every request is evaluated against an ordered validation pipeline. The first check that fails determines the error returned, and later checks are not evaluated — error precedence is therefore deterministic across the whole API.

1. **Header presence.** `X-User-ID` and `X-User-Role` must be present and non-empty, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`.
2. **Role authorization.** The role must appear in the endpoint's authorized roles, else `ERR_UNAUTHORIZED_ROLE`.
3. **Resource scoping.** The mariner self-scope and union-dispatcher own-hall rules of §2.1, else `ERR_FORBIDDEN_RESOURCE_ACCESS`.
4. **Path existence.** Identifiers in the URL are resolved strictly left to right; the first identifier that does not correspond to an existing resource yields that resource's dedicated 404 — for example, a credential action under a non-existent mariner fails with `ERR_MARINER_NOT_FOUND` before the credential id is ever examined, and only a missing credential id surfaces `ERR_CREDENTIAL_NOT_FOUND`. The analogous dedicated identifiers (`ERR_VESSEL_NOT_FOUND`, `ERR_MANNING_SLOT_NOT_FOUND`, `ERR_SEA_SERVICE_RECORD_NOT_FOUND`, `ERR_MEDICAL_CERTIFICATE_NOT_FOUND`, `ERR_DRUG_TEST_NOT_FOUND`, `ERR_TRAINING_COURSE_NOT_FOUND`, `ERR_TRAINING_ENROLLMENT_NOT_FOUND`, `ERR_UNION_HALL_NOT_FOUND`, `ERR_UNION_REGISTRATION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_TRAVEL_BOOKING_NOT_FOUND`, `ERR_ROTATION_PLAN_NOT_FOUND`) are catalogued in §5.
5. **Body foreign keys.** Identifiers supplied in the request payload — `mariner_id`, `manning_slot_id`, `union_registration_id`, `relief_of_assignment_id`, `prerequisite_credential_id` — must each reference an existing resource, else the corresponding resource-not-found error.
6. **Schema.** Required fields must be present, types must be valid, enum membership must be valid, date ranges must be ordered (end on or after start, or strictly after, as each field specifies), `rank_grade` must lie within 1 through 9 inclusive, and the uniqueness constraints on `mariner_reference_number`, `imo_number`, `course_code`, and `local_number` must hold. Any violation is `ERR_INVALID_REQUEST`.
7. **Optimistic concurrency.** For the three version-guarded writes of §2.8, the expected version must match the parent entity's current `version`, else `ERR_STALE_VERSION`.
8. **Segregation of duties.** The sea-service verifier must differ from the recorder, and the reimburser must differ from the approver (§3.4 and §3.9), else `ERR_SOD_VERIFY_SAME_RECORDER` or `ERR_SOD_REIMBURSE_SAME_APPROVER`.
9. **State preconditions.** The target entity must be in the state the transition requires, else `ERR_INVALID_STATE` or the transition-specific error (`ERR_CREDENTIAL_NOT_RENEWABLE`, `ERR_RENEWAL_NOT_PENDING`, `ERR_CREDENTIAL_NOT_VALID`, `ERR_RECORD_NOT_SUBMITTABLE`, `ERR_RECORD_NOT_VERIFIABLE`, `ERR_DRUG_TEST_NOT_PENDING`, `ERR_MEDICAL_CERT_NOT_VALID`, `ERR_COURSE_NOT_SCHEDULED`, `ERR_SIGN_ON_TOO_EARLY`, `ERR_TRAVEL_NOT_READY`, `ERR_RELIEF_NOT_ONBOARD`, `ERR_REPATRIATION_INCOMPLETE`, `ERR_SLOT_NOT_ACTIVE`, `ERR_VESSEL_NOT_ACTIVE`), as named in §3.
10. **Readiness gates.** Mariner posture gates reject with `ERR_MARINER_NOT_CLEAR` or `ERR_RESTRICTED_WINDOW_EXCEEDED` (§3.2).
11. **Endorsement and rank chain.** `ERR_ENDORSEMENT_MISMATCH`, `ERR_ENDORSEMENT_PREREQUISITE_INVALID`, `ERR_UPGRADE_REQUIREMENTS_NOT_MET`, `ERR_RANK_BELOW_MINIMUM` (§3.3, §3.7).
12. **Channel rules.** `ERR_CHANNEL_NOT_PERMITTED`, `ERR_UNION_REGISTRATION_INVALID`, `ERR_DUES_NOT_CURRENT` (§3.7).
13. **Temporal windowing.** Rotation-window coverage first, then mariner overlap, then slot handover: `ERR_NO_ACTIVE_ROTATION_WINDOW`, `ERR_MARINER_ASSIGNMENT_OVERLAP`, `ERR_HANDOVER_WINDOW_EXCEEDED` (§3.7).
14. **Aggregate and uniqueness constraints.** `ERR_COURSE_FULL`, `ERR_DUPLICATE_ENROLLMENT`, `ERR_DUPLICATE_REGISTRATION`, `ERR_NO_MANNING_SLOTS`, `ERR_ACTIVE_CREW_ABOARD`, `ERR_SLOT_HAS_OPEN_ASSIGNMENTS`, `ERR_TRAINING_PRIVILEGES_SUSPENDED`, `ERR_MARINER_NOT_ACTIVE` (§3).
15. **Fiscal gate.** The training-budget availability check at enrollment rejects with `ERR_TRAINING_BUDGET_EXCEEDED` (§3.9).

### 2.6. The Logical Clock and the Expiry Sweep

All time-dependent rules in this system evaluate against a logical clock, never against wall-clock time. Before any clock-setting call, the clock reads exactly 2026-08-01T00:00:00Z. A `FleetAdmin` may advance the clock by supplying a `to_iso8601` instant; reading the clock returns `current_utc`. Setting the clock is not a passive write: it synchronously executes the expiry sweep in the following pinned order, all within the same call.

1. Credentials in `VALID`, `RENEWAL_PENDING`, or `SUSPENDED_PREREQ` whose `expiry_date` is strictly earlier than the new clock become `EXPIRED`.
2. Credentials already `EXPIRED` whose `expiry_date` lies more than 180 days before the new clock become `LAPSED` — a 180-day late-renewal grace, after which a credential can never be renewed again.
3. The prerequisite cascade runs: dependents of newly expired or revoked credentials move to `SUSPENDED_PREREQ`, and dependents of credentials that returned to `VALID` move back to `VALID` (§3.3).
4. Medical certificates in `VALID` or `SUSPENDED` whose `expiry_date` is strictly earlier than the new clock become `EXPIRED`.
5. The `readiness_posture` of every affected mariner is recomputed (§3.2).
6. Mariners whose posture became `BLOCKED` have their confirmed assignments suspended (§3.7).
7. Slot coverage and vessel compliance postures are recomputed for every affected slot and vessel (§3.6).

Expiry comparisons are strict: a credential or certificate whose `expiry_date` is exactly the current clock instant remains valid; it expires only once the clock moves strictly past that instant.

### 2.7. Precision: Money, Days, and Time

All monetary amounts in this system are integers denominated in cents. Where a calculation multiplies (fares, markups, reimbursement percentages, cancellation fees), the result is rounded half-up to whole cents at the multiplication step specified in §3; no intermediate floating-point representation is exposed. Sea-service day credits are expressed on a half-day grid: day totals are floored to the nearest half day (multiply by two, round down to a whole number, divide by two). All datetime comparisons are evaluated at second precision, and boundary instants are inclusive wherever a rule says "on or after" — an expiry exactly equal to now still counts as valid, and a currency window exactly equal to now still counts as current. Every datetime value the API returns is likewise rendered as an ISO 8601 UTC timestamp at whole-second precision — `YYYY-MM-DDTHH:MM:SSZ`, exactly as in the clock reading `2026-08-01T00:00:00Z` of §2.6. This covers every domain datetime field (for example `issue_date`, `expiry_date`, `start_date`, `end_date`, `scheduled_date`, `collected_date`, `seniority_date`, `dues_current_until`, `sign_on_date`, `planned_relief_date`, `actual_sign_on_at`, `actual_relieved_at`, travel-leg `depart_at` and `arrive_at`, `drug_test_current_until`, and rotation-plan `effective_from` and `effective_to`), the clock's `current_utc`, and computed-read fields such as the upgrade-eligibility `window_start`; the three-fractional-digit form is reserved for `created_at` and `updated_at` (§2.4) and the envelope's `api_request_timestamp` (§2.2) only.

### 2.8. Optimistic Concurrency Control

Exactly three write operations are guarded by optimistic concurrency control, and each names a non-optional expected-version field in its request body:

- Revising a manning billet requires `expected_manning_slot_version`, carrying the client's last observed `version` of that ManningSlot. If the slot's current `version` no longer matches — because another writer has changed the billet since the caller last observed it — the revision is based on a stale safe-manning document and is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Creating a rotation plan for a vessel requires `expected_vessel_version`, carrying the client's last observed `version` of that Vessel. Because plan creation legitimately supersedes the vessel's prior active plan, a mismatch means another writer has already created or otherwise changed rotation state since the caller last observed the vessel, and the new plan would supersede a plan the caller never saw; the create is rejected with `ERR_STALE_VERSION` (HTTP 412).
- Editing a mariner profile requires `expected_mariner_version`, carrying the client's last observed `version` of that Mariner. A mismatch — the version advanced by cascading side effects such as credential sweeps, posture recomputes, or assignment suspensions, or by another writer's edit — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No endpoint other than these three takes a version field.

### 2.9. Derived Postures and Cascading Consistency

Two derived postures anchor cross-aggregate behavior. A mariner's `readiness_posture` (`CLEAR`, `RESTRICTED`, or `BLOCKED`, with a `readiness_reasons` list) summarizes whether the mariner may be crewed, and a vessel's `compliance_posture` (`COMPLIANT`, `DEFICIENT`, or `CRITICAL_SHORTAGE`, with `slots_total` and `slots_covered`) summarizes whether the vessel may sail. Both are always computed from the current committed child rows, evaluated against the pre-transition snapshot: posture is computed before the gated transition's own writes are applied, and a transition never re-enters the posture computation for itself. This pinned evaluation order resolves the otherwise circular dependency between posture gating assignment confirmation and assignment writes feeding back into mariner state.

Whenever the underlying children change — a credential revoked or swept, a medical certificate suspended or expired, a drug result recorded, an assignment signed on, relieved, suspended, resumed, or cancelled, a billet defined or retired — the affected postures are recomputed immediately, and cascading transitions follow: a mariner who becomes `BLOCKED` sees their open assignments suspended; a billet losing its on-board coverage may drag the vessel's posture down. Each cascade mutates the resources it touches, refreshing their `updated_at` and incrementing their `version` per §2.4.

## 3. Business Logic & Workflows

### 3.1. Mariner Registration and Lifecycle

A `FleetAdmin` registers a mariner with `full_name`, a `mariner_reference_number` unique across all mariners, a `home_port_code` (for example SFO or NOLA), a default sourcing `hire_channel` of `DIRECT` or `UNION_HALL`, a `rank_track` of `DECK`, `ENGINE`, or `STEWARD`, a `rank_grade` from 1 (lowest) through 9 (highest), and the `primary_endorsement_code` the mariner must hold as a valid credential to be postured clear (for example DECK_AB or CHIEF_MATE). The optional `annual_training_cap_cents` seeds the mariner's yearly training budgets and defaults to 500,000 cents (five thousand dollars) when omitted. A newly registered mariner starts in `APPLICANT` status with `training_privileges` `ENABLED`, a `no_show_strike_count` of zero, and a computed `readiness_posture` of `BLOCKED` carrying the reason `STATUS_NOT_ACTIVE` — applicants are not crewable until activated. The registry can be browsed with filters on `status`, `readiness_posture`, `home_port_code`, and `hire_channel`, and a single-mariner fetch exposes the computed `readiness_posture`, `readiness_reasons`, and `drug_test_current_until` alongside the stored fields.

Activation moves a mariner from `APPLICANT` to `ACTIVE` and enforces three gates, each of which fails with `ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING`: at least one medical certificate in `VALID` status whose `expiry_date` is on or after now; at least one completed drug test with result `NEGATIVE` whose `collected_date` extended by 365 days is on or after now; and at least one credential in `VALID` status. Activation recomputes the mariner's posture.

Suspension moves an `ACTIVE` mariner to `SUSPENDED`, forces posture to `BLOCKED` with reason `STATUS_NOT_ACTIVE`, and cascades: every `CONFIRMED` assignment of the mariner moves to `SUSPENDED`, with slot coverage and vessel compliance recomputed accordingly. Reinstatement moves `SUSPENDED` back to `ACTIVE`, but only after the same three activation gates are re-checked — medical validity, drug currency, and a valid credential — failing which the reinstatement is rejected with `ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING`.

Termination is allowed from `ACTIVE` or `SUSPENDED` and is blocked while any assignment of the mariner is `ONBOARD`, rejected with `ERR_ACTIVE_CREW_ABOARD`. Termination forces posture to `BLOCKED` and unwinds the mariner's open commitments: every `PROPOSED` and `CONFIRMED` assignment moves to `CANCELLED`, with their non-terminal travel bookings cancelled in cascade (ticketed bookings accruing the cancellation fee of §3.8); every `REQUESTED` training enrollment moves to `REJECTED`; and every `APPROVED` enrollment moves to `CANCELLED`. `TERMINATED` is terminal.

A `FleetAdmin` may edit a mariner's profile — `full_name`, `home_port_code`, `hire_channel`, `rank_track`, `rank_grade`, `primary_endorsement_code`, `annual_training_cap_cents` — under the optimistic-concurrency rule of §2.8 (`expected_mariner_version` required). When `primary_endorsement_code` changes, the mariner's `readiness_posture` is recomputed, since the fifth readiness gate keys on it.

### 3.2. The Readiness Posture: Gates, Reasons, and the Restricted Window

A mariner's `readiness_posture` is recomputed whenever the mariner's `status` changes, whenever any of the mariner's credential, medical-certificate, or drug-test children is created or mutated, and on every clock sweep. The evaluation walks five gates in a fixed order, collecting every applicable reason code into `readiness_reasons`; a mariner who fails several of the later gates accumulates each failing gate's reason.

The first gate is lifecycle: if `status` is `APPLICANT`, `SUSPENDED`, or `TERMINATED`, posture is `BLOCKED` with reason `STATUS_NOT_ACTIVE`, and the remaining gates are skipped. The second gate is medical: if no medical certificate exists in `VALID` status with an `expiry_date` on or after now, posture is `BLOCKED` with reason `NO_VALID_MEDICAL`. The third gate is drug currency: `drug_test_current_until` is the latest `collected_date` among the mariner's completed tests with result `NEGATIVE` and `test_type` one of `PRE_EMPLOYMENT`, `PERIODIC`, `RANDOM`, or `RETURN_TO_DUTY`, extended by 365 days; a mariner with no qualifying negative test has no currency date at all. If that date is absent or strictly earlier than now, posture is `BLOCKED` with reason `DRUG_CURRENCY_LAPSED` — note that `REASONABLE_CAUSE` results never extend currency. The fourth gate inspects the latest result: if the mariner's most recent completed test — latest by `collected_date`, ties broken by `created_at` — has result `POSITIVE` or `REFUSAL`, posture is `BLOCKED` with reason `DRUG_RESULT_POSITIVE`. The fifth gate is the primary credential: if no credential exists in `VALID` status whose `endorsement_code` equals the mariner's `primary_endorsement_code`, posture is `BLOCKED` with reason `NO_VALID_PRIMARY_CREDENTIAL`.

When no gate blocks, the system computes the earliest expiry among the satisfying medical certificate's `expiry_date`, the `drug_test_current_until` date, and the primary credential's `expiry_date`. If that earliest expiry falls within 30 days of now, posture is `RESTRICTED` and `readiness_reasons` carries one code per source expiring inside that window — `MEDICAL_EXPIRING_SOON`, `DRUG_CURRENCY_EXPIRING_SOON`, or `CREDENTIAL_EXPIRING_SOON`. Otherwise posture is `CLEAR` with an empty reason list. The `RESTRICTED` semantic matters at crewing time: a restricted mariner may be confirmed onto an assignment only when the assignment's `planned_relief_date` is on or before the earliest restricting expiry; confirming beyond that horizon is rejected with `ERR_RESTRICTED_WINDOW_EXCEEDED`, while a `BLOCKED` mariner is rejected outright with `ERR_MARINER_NOT_CLEAR`.

### 3.3. Credentials, Endorsements, and Prerequisite Chains

A `CredentialingOfficer` issues credentials to a mariner, supplying `credential_type` (one of `MMC_BASE`, `OFFICER_ENDORSEMENT`, `STCW`, `TANKER`, `SPECIAL`), an `endorsement_code` (for example DECK_AB, OICNW, CHIEF_MATE, MASTER, STCW_II_1), an `issue_date`, an `expiry_date`, and optionally a `prerequisite_credential_id` forming a self-referential chain within the same mariner's inventory. A credential is valid while its `expiry_date` is on or after the current clock. The prerequisite, when supplied, must belong to the same mariner and must itself be `VALID` at issuance, else the issuance is rejected with `ERR_ENDORSEMENT_PREREQUISITE_INVALID`. A regulated upgrade — an `OFFICER_ENDORSEMENT` whose `endorsement_code` is one of the recognized upgrade targets CHIEF_MATE, MASTER, or SECOND_ENGINEER — additionally requires the mariner's upgrade eligibility (§3.4) to hold for that target, else `ERR_UPGRADE_REQUIREMENTS_NOT_MET`. A newly issued credential starts `VALID` with `renewal_count` zero, and issuance recomputes the mariner's posture — a fresh primary credential can lift a `NO_VALID_PRIMARY_CREDENTIAL` block. Credentials can be listed per mariner (filterable by `status`), fetched individually, or searched through a flat listing filterable by `mariner_id`, `prerequisite_credential_id`, `status`, and `endorsement_code`, which supports prerequisite-chain discovery.

The renewal loop runs `VALID` → `RENEWAL_PENDING` → `VALID`. The mariner themself, or a `CredentialingOfficer`, submits a renewal for a credential in `VALID` or `EXPIRED` status — anything else is `ERR_CREDENTIAL_NOT_RENEWABLE`. Late renewal from `EXPIRED` is reachable only within the 180-day grace window, before the sweep moves the credential to `LAPSED`. Approving a renewal — a `CredentialingOfficer` capability — requires the credential to be `RENEWAL_PENDING` (else `ERR_RENEWAL_NOT_PENDING`), requires `new_expiry_date` to be strictly later than `new_issue_date` and strictly later than now (else `ERR_INVALID_REQUEST`), and, when a `prerequisite_credential_id` is set, requires the prerequisite to be `VALID` (else `ERR_ENDORSEMENT_PREREQUISITE_INVALID`). Approval replaces `issue_date` with `new_issue_date` and `expiry_date` with `new_expiry_date`, increments `renewal_count` by one, and restores any dependent credentials sitting in `SUSPENDED_PREREQ` back to `VALID`. Denying a renewal — with an optional `reason` — also returns the credential to `VALID`, but keeps the old dates unchanged, so a credential whose `expiry_date` has already passed is simply re-expired by the next clock sweep. Both decisions recompute the mariner's posture, and neither one automatically resumes assignments: assignments suspended by an earlier posture flip stay `SUSPENDED` until a `CrewingManager` resumes them (§3.7).

Revocation moves a `VALID` credential to `REVOKED` — any other source state is `ERR_CREDENTIAL_NOT_VALID` — and requires a `reason`. Revocation cascades down the prerequisite chain: every dependent credential (one whose `prerequisite_credential_id` points at the revoked credential) in `VALID` or `RENEWAL_PENDING` moves to `SUSPENDED_PREREQ`. The mariner's posture is then recomputed and may flip to `BLOCKED` with reason `NO_VALID_PRIMARY_CREDENTIAL`; when it does, the mariner's confirmed assignments are suspended and slot coverage and vessel compliance are recomputed, per §3.7. A credential stranded in `SUSPENDED_PREREQ` can also be manually reinstated to `VALID` by a `CredentialingOfficer`, but only when its prerequisite is already `VALID`, else `ERR_ENDORSEMENT_PREREQUISITE_INVALID`.

Time itself moves credentials. The clock sweep (§2.6) expires any credential in `VALID`, `RENEWAL_PENDING`, or `SUSPENDED_PREREQ` whose `expiry_date` is strictly before now, and lapses any credential already `EXPIRED` more than 180 days past its expiry; `REVOKED` and `LAPSED` are terminal, and a lapsed credential can never be renewed. The same prerequisite cascade fires on expiry and lapsing as on revocation: dependents in `VALID` or `RENEWAL_PENDING` fall to `SUSPENDED_PREREQ`, each such transition recomputing the mariner's posture, with the confirmed-assignment suspension cascade following whenever the posture lands on `BLOCKED`. When a prerequisite returns to `VALID` through an approved renewal, its `SUSPENDED_PREREQ` dependents are restored to `VALID` automatically.

### 3.4. Sea Service: Documentation, Verification, and Upgrade Eligibility

Sea service is entered by the mariner themself, or by a `CredentialingOfficer` on the mariner's behalf, with the serving `vessel_id`, a free-form `position_code`, the `rank_track` served (`DECK`, `ENGINE`, or `STEWARD`), the `rank_grade` served at (1 through 9), a `service_region` of `OCEAN`, `NEAR_COASTAL`, `INLAND`, or `GREAT_LAKES`, a `watch_schedule` of `EIGHT_HOUR` or `TWELVE_HOUR`, and inclusive `start_date` and `end_date`. The record is created in `DRAFT` status, stamped with `entered_by_user_id` from `X-User-ID`, and its `provisional_days` is computed immediately as the inclusive calendar-day count — the whole-day difference between `end_date` and `start_date`, plus one — with no regional or watch factors applied. The `end_date` must be on or after `start_date` and not later than the current clock, else `ERR_INVALID_REQUEST`. Records can be listed per mariner (filterable by `record_status`), listed per vessel, or fetched individually.

Submission moves a record from `DRAFT` to `SUBMITTED`, re-checking that `end_date` is on or after `start_date` and not in the future (else `ERR_INVALID_REQUEST`); from any other state the submission is `ERR_RECORD_NOT_SUBMITTABLE`. Verification moves `SUBMITTED` to `VERIFIED` (else `ERR_RECORD_NOT_VERIFIABLE`) under a segregation-of-duties rule: the verifying officer's `X-User-ID` must differ from the record's `entered_by_user_id`, else `ERR_SOD_VERIFY_SAME_RECORDER` (HTTP 403). Verification computes `verified_days` — null until this point — as the inclusive calendar-day count multiplied by the region factor and the watch multiplier, floored to the half-day grid, and stamps `verified_by_user_id` with the verifier's `X-User-ID`. The region factor grants full credit (1.0) for `OCEAN`, `NEAR_COASTAL`, and `GREAT_LAKES` service, and half credit (0.5) for `INLAND`; the watch multiplier grants 1.5 times credit for `TWELVE_HOUR` schedules and single credit for `EIGHT_HOUR`. A 30-day ocean hitch on twelve-hour watches therefore verifies as 45.0 days, while the same 30 days inland on eight-hour watches verifies as 15.0.

Dispute moves a `SUBMITTED` record to `DISPUTED` (else `ERR_RECORD_NOT_VERIFIABLE`), recording the supplied `reason` into `dispute_reason`. A disputed record may be resubmitted — the same submission action carries `DISPUTED` back to `SUBMITTED` — or rejected outright: rejection moves `SUBMITTED` or `DISPUTED` to the terminal `REJECTED` state (any other source state is `ERR_RECORD_NOT_VERIFIABLE`) and requires a `reason`. `VERIFIED` and `REJECTED` are the terminal states of the record lifecycle.

Two computed reads aggregate this history. The sea-service summary returns `provisional_days_total` — the sum of `provisional_days` over records in `SUBMITTED` or `VERIFIED` — `verified_days_total` — the sum of `verified_days` over `VERIFIED` records only — and a `by_track` breakdown; `DRAFT`, `DISPUTED`, and `REJECTED` records are excluded from both totals. The upgrade-eligibility read evaluates a mariner against a `target_endorsement_code`; an unrecognized target is rejected with `ERR_INVALID_REQUEST`. The recognized targets and their requirements: CHIEF_MATE demands 360 days within a 36-month lookback in the `DECK` track at serving grade 4 or higher; MASTER demands the same 360 days and 36-month window in `DECK` at grade 6 or higher; SECOND_ENGINEER demands 270 days within 36 months in the `ENGINE` track at grade 4 or higher. Qualifying days are the summed `verified_days` of `VERIFIED` records whose `rank_track` matches, whose `rank_grade` is at least the required serving grade, and whose `start_date` falls inside the lookback window (now minus the lookback in calendar months). The day threshold is inclusive — exactly 360.0 qualifies, 359.5 does not — and the course requirement demands a training enrollment of this mariner in `COMPLETED` or `REIMBURSED` status whose course's `grants_endorsement_code` equals the target. The response reports `eligible` (both the day threshold and the course requirement met), `target_endorsement_code`, `verified_days_in_window`, `required_days`, `course_requirement_met`, `shortfall_days` (the gap between required and actual days, floored at zero), and `window_start`.

### 3.5. Medical Certificates and the Drug-Test Program

A `CredentialingOfficer` issues medical certificates with a `cert_type` of `USCG_MEDICAL`, `FLAG_STATE_MEDICAL`, or `FIT_FOR_DUTY`, an `issue_date`, an `expiry_date`, and an optional `limitations` list that defaults to empty. A certificate is created `VALID` and remains valid while its `expiry_date` is on or after the current clock; issuance recomputes the mariner's posture. Certificates are listed per mariner, filterable by `status`.

Suspending a certificate moves `VALID` to `SUSPENDED` (any other source state is `ERR_MEDICAL_CERT_NOT_VALID`). A suspended certificate does not satisfy the medical gate, so the posture recompute that follows will typically land the mariner on `BLOCKED` with reason `NO_VALID_MEDICAL` — and when it does, the mariner's confirmed assignments are suspended in cascade (§3.7). Reinstatement moves `SUSPENDED` back to `VALID` (else `ERR_MEDICAL_CERT_NOT_VALID`), provided the `expiry_date` is still in the future. The clock sweep expires any certificate in `VALID` or `SUSPENDED` whose `expiry_date` is strictly before now; `EXPIRED` is terminal.

The drug-test program works the same two-step shape. A `CredentialingOfficer` schedules a test with a `test_type` of `PRE_EMPLOYMENT`, `PERIODIC`, `RANDOM`, `REASONABLE_CAUSE`, or `RETURN_TO_DUTY` and a `scheduled_date`; the record is created `PENDING`. Recording a result moves `PENDING` to `COMPLETED` (else `ERR_DRUG_TEST_NOT_PENDING`) with a `result` of `NEGATIVE`, `POSITIVE`, or `REFUSAL` (anything else is `ERR_INVALID_REQUEST`) and the supplied `collected_date`, stamping `recorded_by_user_id` with the recorder's `X-User-ID`. A `NEGATIVE` result recomputes `drug_test_current_until` — the latest qualifying negative `collected_date` extended by 365 days — and recomputes posture. A `POSITIVE` or `REFUSAL` result forces the mariner's posture to `BLOCKED` with reason `DRUG_RESULT_POSITIVE` and suspends every confirmed assignment of the mariner, with slot coverage and vessel compliance recomputed. Tests are listed per mariner, filterable by `status` and `result`.

### 3.6. Vessels, Safe Manning, and Rotation Planning

A `FleetAdmin` registers a vessel with `vessel_name`, an `imo_number` unique across all vessels, a `vessel_class` of `TANKER`, `CONTAINER`, `BULK`, `PASSENGER`, or `OSV`, and a `flag_state`. The vessel is created `REGISTERED`, and its `compliance_posture` computes to `COMPLIANT` over the empty slot set. Vessels can be listed with filters on `status` and `vessel_class`; a single-vessel fetch exposes the computed `compliance_posture`, `slots_total`, and `slots_covered`.

The safe manning document is built billet by billet. While a vessel is `REGISTERED` or `ACTIVE`, a `PortCaptain` defines manning slots with a `position_code` (MASTER, CHIEF_MATE, OICNW, AB, CHIEF_ENGINEER, SECOND_ENGINEER, QMED, COOK, and the like), a required `rank_track`, a `min_rank_grade` from 1 through 9, the `required_endorsement_code` a filler's valid credential must carry, an `is_critical_position` flag defaulting to false, and the billet's `standard_tour_days`. A new billet starts `ACTIVE` with `current_coverage` `UNCOVERED`, and the vessel's posture and slot totals are recomputed. Revising a billet — any of `position_code`, `rank_track`, `min_rank_grade`, `required_endorsement_code`, `is_critical_position`, `standard_tour_days` — is likewise a `PortCaptain` capability, guarded by `expected_manning_slot_version` per §2.8, permitted only while no open assignment (in `PROPOSED`, `CONFIRMED`, `ONBOARD`, or `SUSPENDED`) references the billet, else `ERR_SLOT_HAS_OPEN_ASSIGNMENTS`; a change to `is_critical_position` recomputes the vessel's posture. Retiring a billet moves `ACTIVE` to the terminal `RETIRED` under the same open-assignment embargo (`ERR_SLOT_HAS_OPEN_ASSIGNMENTS`) and recomputes the vessel's `compliance_posture`, `slots_total`, and `slots_covered`.

Coverage is exact set semantics. A billet's `current_coverage` is `COVERED` exactly when an assignment on that slot is `ONBOARD`, and `UNCOVERED` otherwise. `slots_total` counts the vessel's `ACTIVE` billets; `slots_covered` counts those that are `COVERED`. The vessel's `compliance_posture` is `CRITICAL_SHORTAGE` when any `ACTIVE` billet flagged `is_critical_position` is uncovered, else `DEFICIENT` when any `ACTIVE` billet is uncovered, else `COMPLIANT`. The manning-compliance snapshot read returns `posture`, `slots_total`, `slots_covered`, and the identifiers of the uncovered billets split as `uncovered_critical_slot_ids` and `uncovered_noncritical_slot_ids`.

The vessel lifecycle gates movement on that posture. Activation moves `REGISTERED` to `ACTIVE` and requires at least one `ACTIVE` billet, else `ERR_NO_MANNING_SLOTS`; it recomputes posture. Marking a vessel underway — a `PortCaptain` action moving `ACTIVE` to `UNDERWAY` — proceeds freely from `COMPLIANT`, proceeds from `DEFICIENT` only when a non-empty `waiver_justification` is supplied, and is always rejected from `CRITICAL_SHORTAGE` with `ERR_VESSEL_NOT_COMPLIANT`; returning to port moves `UNDERWAY` back to `ACTIVE`. Laying up — `ACTIVE` to `LAID_UP`, again a `PortCaptain` action — requires that no assignment on any of the vessel's slots be `ONBOARD`, else `ERR_ACTIVE_CREW_ABOARD`, and cascades every `PROPOSED` and `CONFIRMED` assignment on the vessel's slots to `CANCELLED`, with their non-terminal travel bookings cancelled in cascade (ticketed ones accruing the fee of §3.8). Decommissioning — a `FleetAdmin` action — moves `ACTIVE` or `LAID_UP` to the terminal `DECOMMISSIONED`; from `ACTIVE` it is blocked while any assignment on the vessel's slots is in `PROPOSED`, `CONFIRMED`, `ONBOARD`, or `SUSPENDED` (`ERR_ACTIVE_CREW_ABOARD`), while from `LAID_UP` it is unconditional. Either path retires every billet of the vessel and supersedes its active rotation plan, if one exists.

Rotation plans govern tour lengths and handover windows. A `CrewingManager` creates a plan for a vessel — the vessel must be `ACTIVE` or `UNDERWAY`, else `ERR_VESSEL_NOT_ACTIVE` — supplying `effective_from` (the inclusive window start governing sign-on dates), `effective_to` (the exclusive window end), a default `standard_tour_days`, and `max_handover_overlap_days`, the maximum whole-day overlap permitted between incoming and outgoing assignments on one billet, defaulting to 3 when omitted. Creation carries `expected_vessel_version` per §2.8, and because the new plan is immediately `ACTIVE` and supersedes the vessel's prior `ACTIVE` plan — at most one plan per vessel is ever `ACTIVE` — the vessel's `version` advances by one. A superseded plan can later be moved from `SUPERSEDED` to `ARCHIVED` by a `CrewingManager`; plans are listed per vessel, filterable by `status`.

### 3.7. Crew Assignment and the Two Dispatch Channels

An assignment proposal names the `mariner_id`, the target `manning_slot_id`, an `assignment_channel` of `DIRECT_HIRE` or `UNION_DISPATCH`, a `sign_on_date` that may not be earlier than the current clock, a `planned_relief_date` strictly after the sign-on date, and optionally a `relief_of_assignment_id` linking the outgoing assignment this one relieves, a `union_registration_id` (required exactly when the channel is `UNION_DISPATCH`), and a `local_join` flag defaulting to false for mariners already at port. The vessel is denormalized onto the assignment as `vessel_id` from the billet's vessel. A new assignment is `PROPOSED`, with `travel_status` `PENDING` and `repatriation_status` `NOT_DUE`. Proposals are made by a `CrewingManager` for the direct channel or a `UnionDispatcher` for the union channel, and the creation-time gate battery rejects: a vessel not in `ACTIVE` or `UNDERWAY` (`ERR_VESSEL_NOT_ACTIVE`); a billet not in `ACTIVE` status (`ERR_SLOT_NOT_ACTIVE`); a mariner whose `status` is not `ACTIVE` (`ERR_MARINER_NOT_ACTIVE`); a mariner whose posture is `BLOCKED` (`ERR_MARINER_NOT_CLEAR`); a filler lacking a `VALID` credential carrying the billet's `required_endorsement_code` (`ERR_ENDORSEMENT_MISMATCH`); a mariner whose `rank_track` differs from the billet's `rank_track` or whose `rank_grade` is below the billet's `min_rank_grade` (`ERR_RANK_BELOW_MINIMUM`); and the channel, temporal, and union rules below. Assignments are listed with filters on `mariner_id`, `manning_slot_id`, `vessel_id`, `assignment_status`, `relief_of_assignment_id`, and `union_registration_id`.

Channel rules are enforced at both proposal and confirmation. A `DIRECT_HIRE` assignment requires the acting role to be `CrewingManager` and the mariner's `hire_channel` to be `DIRECT`. A `UNION_DISPATCH` assignment requires the acting role to be `UnionDispatcher`, the mariner's `hire_channel` to be `UNION_HALL`, the referenced registration to be in `REGISTERED` status, and the registration's `dues_current_until` to be on or after the `sign_on_date` — violations surface as `ERR_CHANNEL_NOT_PERMITTED`, `ERR_UNION_REGISTRATION_INVALID`, or `ERR_DUES_NOT_CURRENT`, and a dispatcher acting outside their own hall is `ERR_FORBIDDEN_RESOURCE_ACCESS`.

The union side of the channel is administered as follows. A `FleetAdmin` registers union halls with a unique `local_number`, a `name`, and a `region`. Registering a mariner with a hall — a `UnionDispatcher` acting on their own hall, or a `FleetAdmin` — requires the mariner's `hire_channel` to be `UNION_HALL` (else `ERR_CHANNEL_NOT_PERMITTED`) and supplies `mariner_id`, `seniority_date`, and `shipping_card_number`; the hall is recorded on the registration as `hall_id`. The registration is created `REGISTERED` with `dues_current_until` initialized to the `seniority_date`, and a second non-`SUSPENDED` registration for the same hall and mariner is `ERR_DUPLICATE_REGISTRATION`. Dues are extended by the hall's own `UnionDispatcher` supplying a `new_dues_current_until`, which must be strictly later than the current `dues_current_until` (else `ERR_INVALID_REQUEST`) and is only accepted while the registration is `REGISTERED`. Registrations move `REGISTERED` → `SUSPENDED` and back to `REGISTERED` (any other source state is `ERR_INVALID_STATE`), actions open to the hall's dispatcher or a `FleetAdmin`. Registrations are listed per hall and per mariner, filterable by `status`.

Confirmation moves `PROPOSED` to `CONFIRMED` — any other source state is `ERR_INVALID_STATE` — and re-runs the full gate battery against the now-current state of the world: the acting role must match the `assignment_channel` (a `CrewingManager` for `DIRECT_HIRE`, the registration's own-hall `UnionDispatcher` for `UNION_DISPATCH`, else `ERR_CHANNEL_NOT_PERMITTED` or `ERR_FORBIDDEN_RESOURCE_ACCESS`); the mariner's posture must be `CLEAR`, or `RESTRICTED` with the `planned_relief_date` on or before the earliest restricting expiry (else `ERR_MARINER_NOT_CLEAR` or `ERR_RESTRICTED_WINDOW_EXCEEDED`); the mariner must still hold a `VALID` credential with the billet's `required_endorsement_code` (else `ERR_ENDORSEMENT_MISMATCH`); track and grade are re-checked (else `ERR_RANK_BELOW_MINIMUM`); the overlap checks below are re-run; and for union dispatch the registration and dues checks are re-run. When several violations coexist, the pipeline order of §2.5 decides which error surfaces. A confirmed assignment's `travel_status` is set to `WAIVED` when `local_join` is true, and remains `PENDING` otherwise.

Temporal windowing applies its three checks in a fixed order. First, the rotation-window gate: the vessel must have an `ACTIVE` rotation plan whose `effective_from` is on or before the `sign_on_date` and whose `effective_to` is strictly after it, else `ERR_NO_ACTIVE_ROTATION_WINDOW`. Second, mariner double-booking uses strict half-open interval semantics with zero tolerance: over the mariner's own assignments in `CONFIRMED`, `ONBOARD`, or `SUSPENDED`, an overlap exists exactly when the new `sign_on_date` is strictly before the existing `planned_relief_date` and the existing `sign_on_date` is strictly before the new `planned_relief_date`; touching endpoints — a new sign-on exactly equal to an existing planned relief — do not overlap, and a true overlap is `ERR_MARINER_ASSIGNMENT_OVERLAP`. Third, slot handover is a bounded buffer: over the other assignments on the same billet in `CONFIRMED` or `ONBOARD`, the overlap in whole days is the earlier of the two `planned_relief_date` values minus the later of the two `sign_on_date` values, floored to whole days with a negative result treated as zero; the handover is allowed only when that overlap is at most the active plan's `max_handover_overlap_days` — equality is allowed — else `ERR_HANDOVER_WINDOW_EXCEEDED`.

Sign-on moves `CONFIRMED` to `ONBOARD` and is open to a `CrewingManager` or `PortCaptain`. It requires the current clock to be at or past the `sign_on_date` (else `ERR_SIGN_ON_TOO_EARLY`), the `travel_status` to be `READY` or `WAIVED` (else `ERR_TRAVEL_NOT_READY`), and the mariner's posture to be anything but `BLOCKED` (else `ERR_MARINER_NOT_CLEAR`). Sign-on stamps `actual_sign_on_at` with the current clock, flips the billet's `current_coverage` to `COVERED`, and recomputes the vessel's `slots_covered` and `compliance_posture`.

Suspension and resume form the mid-tour loop. Whenever a mariner's posture flips to `BLOCKED` — through a credential, medical, or drug cascade, or through manual suspension — the system moves every `CONFIRMED` assignment of that mariner to `SUSPENDED` (no coverage change follows, since a confirmed assignment does not cover its billet) and every `ONBOARD` assignment to `SUSPENDED` as well, uncovering that billet and recomputing the vessel's posture, which may degrade to `DEFICIENT` or `CRITICAL_SHORTAGE`. Resumption is a `CrewingManager` action and branches on whether the mariner ever signed on: a suspended assignment whose `actual_sign_on_at` was never set returns to `CONFIRMED`, requiring posture `CLEAR` or `RESTRICTED` within the window rule of §3.2 (else `ERR_MARINER_NOT_CLEAR` or `ERR_RESTRICTED_WINDOW_EXCEEDED`), while one whose `actual_sign_on_at` is set returns directly to `ONBOARD`, requiring posture `CLEAR` or `RESTRICTED` (else `ERR_MARINER_NOT_CLEAR`), with coverage and vessel posture recomputed. Any resume attempted on a non-`SUSPENDED` assignment is `ERR_INVALID_STATE`.

Relief and close finish the tour. Relieving — a `CrewingManager` action — moves `ONBOARD` to `RELIEVED` and requires that another, different assignment on the same billet already be `ONBOARD` (else `ERR_RELIEF_NOT_ONBOARD`); it stamps `actual_relieved_at` with the current clock, moves `repatriation_status` to `DUE`, auto-creates a repatriation travel booking under the relieved assignment (direction `REPATRIATION`, status `QUOTED`, empty `legs`, payer `VESSEL_OWNER`), and leaves the billet `COVERED` through the incoming on-board assignment while the vessel's posture is recomputed. Closing moves `RELIEVED` to the terminal `CLOSED` and requires `repatriation_status` to have reached `COMPLETED` (else `ERR_REPATRIATION_INCOMPLETE`).

Cancellation moves an assignment from `PROPOSED`, `CONFIRMED`, or `SUSPENDED` to the terminal `CANCELLED` — any other source state is `ERR_INVALID_STATE` — and is open to a `CrewingManager`, or to the own-hall `UnionDispatcher` for union-dispatch assignments. Cancelling from `CONFIRMED` or `SUSPENDED` cascades every travel booking of the assignment in `QUOTED`, `BOOKED`, or `TICKETED` to `CANCELLED`, with ticketed bookings accruing the cancellation fee of §3.8, and recomputes coverage and vessel posture.

### 3.8. Travel and Repatriation Logistics

Travel bookings belong to an assignment (recorded as `assignment_id`) and come in two `direction` values: `JOIN` bookings get the mariner to the vessel, and `REPATRIATION` bookings get them home. Only `JOIN` bookings are created manually — a `CrewingManager` capability on an assignment in `CONFIRMED`, `ONBOARD`, or `RELIEVED` status (else `ERR_INVALID_STATE`), and a manual creation naming `REPATRIATION` is rejected with `ERR_INVALID_REQUEST`. Repatriation bookings are created only by the system, at relieve time (§3.7). A `JOIN` creation requires at least one leg, else `ERR_NO_TRAVEL_LEGS`; each leg of the `legs` array carries `carrier`, `from_port`, `to_port`, `depart_at`, `arrive_at`, `base_fare_cents`, and `markup_bps`. The booking also records a `payer` of `VESSEL_OWNER`, `UNION_HALL`, or `MARINER`, and is created in `QUOTED` status. While a booking is `QUOTED`, a `CrewingManager` may replace its `legs` wholesale — this is how the empty system-created repatriation booking gets its itinerary — and replacing legs in any other status is `ERR_INVALID_STATE`. Bookings are listed per assignment, filterable by `direction` and `status`.

The commercial lifecycle runs `QUOTED` → `BOOKED` → `TICKETED` → `COMPLETED`. Booking requires the booking to be `QUOTED` with a non-empty leg list (else `ERR_INVALID_STATE` or `ERR_NO_TRAVEL_LEGS` respectively). Ticketing requires `BOOKED` (else `ERR_INVALID_STATE`) and computes `total_fare_cents`: each leg's fare is its `base_fare_cents` marked up by its `markup_bps` ten-thousandths, rounded half-up to whole cents per leg first, and the per-leg amounts are then summed — the evaluation order is pinned, because rounding per leg before summing yields different cents than summing before rounding. Ticketing also bubbles into the assignment's parallel travel dimensions: a `JOIN` booking reaching `TICKETED` moves the assignment's `travel_status` from `PENDING` to `READY`, and a `REPATRIATION` booking reaching `TICKETED` moves `repatriation_status` from `DUE` to `ARRANGED`. Completion requires `TICKETED` (else `ERR_INVALID_STATE`); a completed `REPATRIATION` booking moves `repatriation_status` from `ARRANGED` to `COMPLETED`.

Cancellation moves a booking from `QUOTED`, `BOOKED`, or `TICKETED` to the terminal `CANCELLED` (else `ERR_INVALID_STATE`), whether by a `CrewingManager`'s explicit action or by the assignment-cancellation cascade of §3.7. Cancelling from `QUOTED` or `BOOKED` sets `cancellation_fee_cents` to zero; cancelling from `TICKETED` sets `cancellation_fee_cents` to 15 percent of `total_fare_cents`, rounded half-up to whole cents. Cancelling a ticketed `JOIN` booking demotes the assignment's `travel_status` back to `PENDING` when no other `JOIN` booking in `TICKETED` or `COMPLETED` status remains.

The two parallel dimensions on the assignment summarize this machinery. `travel_status` runs `PENDING` → `READY` when a join booking is ticketed, `READY` → `PENDING` when the last ticketed-or-completed join booking is cancelled, and `PENDING` → `WAIVED` at confirmation for a local-join mariner. `repatriation_status` runs `NOT_DUE` → `DUE` at relief, `DUE` → `ARRANGED` at repatriation ticketing, and `ARRANGED` → the terminal `COMPLETED` at repatriation completion.

### 3.9. Training: Courses, Enrollment, Budgets, and Reimbursement

A `FleetAdmin` publishes training courses with a unique `course_code`, a `title`, a `provider`, an optional `grants_endorsement_code` naming the endorsement the course satisfies for upgrade eligibility (null when the course grants none), `start_date` and `end_date` with the end on or after the start, a `seat_capacity`, and a `cost_cents` tuition. A course is created `SCHEDULED` with `seats_reserved` zero; its `seats_open` is the `seat_capacity` minus `seats_reserved`, where `seats_reserved` counts enrollments in `ENROLLED`, `COMPLETED`, `NO_SHOW`, or `REIMBURSED` status. Courses are listed filterable by `status`, and a single-course fetch exposes `seats_reserved` and `seats_open`. Cancelling a course — a `FleetAdmin` action requiring `SCHEDULED` (else `ERR_COURSE_NOT_SCHEDULED`) — moves it to the terminal `CANCELLED` and cascades: `REQUESTED` enrollments move to `REJECTED`, `APPROVED` enrollments move to `CANCELLED` with no budget effect, and `ENROLLED` enrollments move to `CANCELLED`, each releasing its budget reservation (the budget's `reserved_cents` reduced by that enrollment's `provisional_amount_cents`) and its seat (`seats_reserved` reduced by one).

Enrollment begins as self-service: a caller with role `Mariner` requests a seat on a course; the enrollment records the course as `course_id`, and its `mariner_id` and `requested_by_user_id` are both taken from `X-User-ID`. Creation requires the course to be `SCHEDULED` (else `ERR_COURSE_NOT_SCHEDULED`), the mariner's `status` to be `ACTIVE` (else `ERR_MARINER_NOT_ACTIVE`), the mariner's `training_privileges` to be `ENABLED` (else `ERR_TRAINING_PRIVILEGES_SUSPENDED`), and no other open enrollment for the same mariner and course in `REQUESTED`, `APPROVED`, `ENROLLED`, or `COMPLETED` status (else `ERR_DUPLICATE_ENROLLMENT`). A new enrollment is `REQUESTED`.

Approval — a `CrewingManager` action — moves `REQUESTED` to `APPROVED` (else `ERR_INVALID_STATE`) and requires the mariner's posture to be anything but `BLOCKED` (else `ERR_MARINER_NOT_CLEAR`); it snapshots the mariner's current `hire_channel` into `channel_snapshot`, which later drives the reimbursement percentage, and stamps `approved_by_user_id` with the approver's `X-User-ID`. Rejection moves `REQUESTED` to the terminal `REJECTED` with an optional `reason`.

Enrollment proper — a `FleetAdmin` action moving `APPROVED` to `ENROLLED` (else `ERR_INVALID_STATE`) — requires the course still `SCHEDULED` (else `ERR_COURSE_NOT_SCHEDULED`), the mariner's posture not `BLOCKED` (else `ERR_MARINER_NOT_CLEAR`), at least one open seat (else `ERR_COURSE_FULL`), and budget headroom. The provisional reservation is computed in a pinned order: the course's `cost_cents` is first capped at the per-course maximum of 200,000 cents (two thousand dollars); the channel percentage is then applied — 100 percent for a `UNION_HALL` `channel_snapshot`, 80 percent for `DIRECT`; and the product is rounded half-up to whole cents as `provisional_amount_cents`. A direct-hire mariner enrolling in a course priced at 250,000 cents therefore reserves 160,000 cents. The budget gate evaluates against the mariner's `TrainingBudget` row for the fiscal year of the course's `start_date`, or against the mariner's `annual_training_cap_cents` when no row exists yet; `available_cents` must be at least the `provisional_amount_cents`, else `ERR_TRAINING_BUDGET_EXCEEDED` (HTTP 402). The budget row is persisted only on a successful enroll — auto-created when absent with `annual_cap_cents` copied from the mariner's `annual_training_cap_cents`, `reserved_cents` and `used_cents` starting at zero, and `fiscal_year` set to the calendar year of the course's `start_date` — at which point `reserved_cents` grows by the provisional amount and the course's `seats_reserved` grows by one. Budget rows are listed per mariner, filterable by `fiscal_year`, and `available_cents` is always the `annual_cap_cents` minus `reserved_cents` minus `used_cents`.

Completion recording — a `FleetAdmin` action on an `ENROLLED` enrollment (else `ERR_INVALID_STATE`) — takes an `outcome` of `COMPLETED` or `NO_SHOW`. A completion retains both the seat and the budget reservation until reimbursement. A no-show releases the budget reservation (`reserved_cents` reduced by `provisional_amount_cents`) but deliberately does not release the seat — `seats_reserved` is unchanged — and increments the mariner's `no_show_strike_count` by one; at two strikes, the mariner's `training_privileges` flip to `SUSPENDED`, and all of the mariner's `REQUESTED` enrollments cascade to `REJECTED` while all `APPROVED` enrollments cascade to `CANCELLED`.

Reimbursement — a `FleetAdmin` action moving `COMPLETED` to the terminal `REIMBURSED` (else `ERR_INVALID_STATE`) — enforces segregation of duties: the reimburser's `X-User-ID` must differ from the enrollment's `approved_by_user_id`, else `ERR_SOD_REIMBURSE_SAME_APPROVER` (HTTP 403). The final `reimbursed_amount_cents` is the lesser of the supplied `receipt_amount_cents` and the `provisional_amount_cents`; the budget's `used_cents` grows by the reimbursed amount while `reserved_cents` is reduced by the full provisional amount, releasing any unreimbursed remainder. The enrollment priced at 250,000 cents above, if submitted with a 150,000-cent receipt, reimburses 150,000 cents and releases the remaining 10,000 cents of reservation. The action stamps `reimbursed_by_user_id` with the reimburser's `X-User-ID`.

An enrollment may also be cancelled from `APPROVED` or `ENROLLED` (else `ERR_INVALID_STATE`) by the mariner themself, a `CrewingManager`, or a `FleetAdmin`; cancelling from `ENROLLED` releases both the seat (`seats_reserved` reduced by one) and the budget reservation (`reserved_cents` reduced by `provisional_amount_cents`). Enrollments are listed per course (staff roles only: `FleetAdmin`, `CrewingManager`, `CredentialingOfficer`, `PortCaptain`, `UnionDispatcher`), per mariner, or fetched individually, with list filters on `status`.

## 4. Endpoint Definitions

Operations that create new resources return a `201 Created` status code; operations that modify an existing resource or drive a state transition return `200 OK`. In the table below, "Any" means all six roles defined in §2.1 — with `Mariner` and `UnionDispatcher` callers still subject to the scoping rules of §2.5. Request payloads, computed fields, and per-endpoint behavior are defined by the narratives of §3 rather than duplicated here.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/mariners` | Register a new mariner | FleetAdmin |
| GET | `/mariners` | List mariners with filters and pagination | Any |
| GET | `/mariners/{id}` | Get one mariner, including computed readiness fields | Any |
| PUT | `/mariners/{id}` | Update mariner profile fields (OCC-guarded) | FleetAdmin |
| POST | `/mariners/{id}/activate` | Activate an applicant after the three activation gates | FleetAdmin |
| POST | `/mariners/{id}/suspend` | Suspend an active mariner, cascading confirmed assignments | FleetAdmin |
| POST | `/mariners/{id}/reinstate` | Reinstate a suspended mariner with gates re-checked | FleetAdmin |
| POST | `/mariners/{id}/terminate` | Terminate a mariner, cascading open assignments and enrollments | FleetAdmin |
| GET | `/mariners/{id}/upgrade-eligibility` | Computed upgrade eligibility against a target endorsement | FleetAdmin, CrewingManager, CredentialingOfficer, PortCaptain, Mariner |
| GET | `/mariners/{id}/sea-service-summary` | Provisional versus verified sea-service totals | FleetAdmin, CrewingManager, CredentialingOfficer, PortCaptain, Mariner |
| POST | `/mariners/{id}/credentials` | Issue a credential or endorsement | CredentialingOfficer |
| GET | `/mariners/{id}/credentials` | List a mariner's credentials | Any |
| GET | `/credentials` | Flat credential list with filters | Any |
| GET | `/credentials/{id}` | Get one credential | Any |
| POST | `/mariners/{id}/credentials/{credentialId}/submit-renewal` | Submit a credential for renewal | Mariner, CredentialingOfficer |
| POST | `/mariners/{id}/credentials/{credentialId}/approve-renewal` | Approve a renewal with new dates | CredentialingOfficer |
| POST | `/mariners/{id}/credentials/{credentialId}/deny-renewal` | Deny a renewal, keeping the old dates | CredentialingOfficer |
| POST | `/mariners/{id}/credentials/{credentialId}/revoke` | Revoke a valid credential | CredentialingOfficer |
| POST | `/mariners/{id}/credentials/{credentialId}/reinstate` | Manually reinstate a prerequisite-suspended credential | CredentialingOfficer |
| POST | `/mariners/{id}/sea-service-records` | Enter a sea-service record | Mariner, CredentialingOfficer |
| GET | `/mariners/{id}/sea-service-records` | List a mariner's sea-service records | Any |
| GET | `/mariners/{id}/sea-service-records/{recordId}` | Get one sea-service record | Any |
| GET | `/vessels/{id}/sea-service-records` | List sea-service records served on a vessel | Any |
| POST | `/mariners/{id}/sea-service-records/{recordId}/submit` | Submit or resubmit a record for verification | Mariner, CredentialingOfficer |
| POST | `/mariners/{id}/sea-service-records/{recordId}/verify` | Verify a submitted record | CredentialingOfficer |
| POST | `/mariners/{id}/sea-service-records/{recordId}/dispute` | Dispute a submitted record with a reason | CredentialingOfficer |
| POST | `/mariners/{id}/sea-service-records/{recordId}/reject` | Reject a submitted or disputed record | CredentialingOfficer |
| POST | `/mariners/{id}/medical-certificates` | Issue a medical certificate | CredentialingOfficer |
| GET | `/mariners/{id}/medical-certificates` | List a mariner's medical certificates | Any |
| POST | `/mariners/{id}/medical-certificates/{certId}/suspend` | Suspend a valid certificate | CredentialingOfficer |
| POST | `/mariners/{id}/medical-certificates/{certId}/reinstate` | Reinstate a suspended certificate | CredentialingOfficer |
| POST | `/mariners/{id}/drug-tests` | Schedule a drug test | CredentialingOfficer |
| GET | `/mariners/{id}/drug-tests` | List a mariner's drug tests | Any |
| POST | `/mariners/{id}/drug-tests/{testId}/record-result` | Record the result of a pending test | CredentialingOfficer |
| POST | `/vessels` | Register a vessel | FleetAdmin |
| GET | `/vessels` | List vessels | Any |
| GET | `/vessels/{id}` | Get one vessel, including computed manning fields | Any |
| POST | `/vessels/{id}/activate` | Activate a registered vessel | FleetAdmin |
| POST | `/vessels/{id}/mark-underway` | Mark a vessel underway, gated on compliance | PortCaptain |
| POST | `/vessels/{id}/return-to-port` | Return an underway vessel to port | PortCaptain |
| POST | `/vessels/{id}/lay-up` | Lay up a vessel with no crew aboard | PortCaptain |
| POST | `/vessels/{id}/decommission` | Decommission a vessel, retiring its billets | FleetAdmin |
| GET | `/vessels/{id}/manning-compliance` | Computed manning compliance snapshot | Any |
| POST | `/vessels/{id}/manning-slots` | Define a billet on the safe manning document | PortCaptain |
| GET | `/vessels/{id}/manning-slots` | List a vessel's billets | Any |
| GET | `/vessels/{id}/manning-slots/{slotId}` | Get one billet | Any |
| PUT | `/vessels/{id}/manning-slots/{slotId}` | Revise a billet (OCC-guarded) | PortCaptain |
| POST | `/vessels/{id}/manning-slots/{slotId}/retire` | Retire a billet with no open assignments | PortCaptain |
| POST | `/vessels/{id}/rotation-plans` | Create a rotation plan, superseding the prior active plan (OCC-guarded) | CrewingManager |
| GET | `/vessels/{id}/rotation-plans` | List a vessel's rotation plans | Any |
| POST | `/vessels/{id}/rotation-plans/{planId}/archive` | Archive a superseded rotation plan | CrewingManager |
| POST | `/assignments` | Propose a crew assignment | CrewingManager, UnionDispatcher |
| GET | `/assignments` | List assignments with filters | Any |
| GET | `/assignments/{id}` | Get one assignment | Any |
| POST | `/assignments/{id}/confirm` | Confirm a proposed assignment (full gate battery) | CrewingManager, UnionDispatcher |
| POST | `/assignments/{id}/sign-on` | Sign a confirmed mariner on board | CrewingManager, PortCaptain |
| POST | `/assignments/{id}/relieve` | Relieve an on-board assignment | CrewingManager |
| POST | `/assignments/{id}/close` | Close a relieved assignment after repatriation | CrewingManager |
| POST | `/assignments/{id}/cancel` | Cancel a proposed, confirmed, or suspended assignment | CrewingManager, UnionDispatcher |
| POST | `/assignments/{id}/resume` | Resume a suspended assignment | CrewingManager |
| POST | `/assignments/{id}/travel-bookings` | Create a join travel booking | CrewingManager |
| GET | `/assignments/{id}/travel-bookings` | List an assignment's travel bookings | Any |
| PUT | `/assignments/{id}/travel-bookings/{bookingId}` | Replace the legs of a quoted booking | CrewingManager |
| POST | `/assignments/{id}/travel-bookings/{bookingId}/book` | Book a quoted itinerary | CrewingManager |
| POST | `/assignments/{id}/travel-bookings/{bookingId}/ticket` | Ticket a booked itinerary, computing the fare | CrewingManager |
| POST | `/assignments/{id}/travel-bookings/{bookingId}/complete` | Complete a ticketed booking | CrewingManager |
| POST | `/assignments/{id}/travel-bookings/{bookingId}/cancel` | Cancel a booking, with a fee when ticketed | CrewingManager |
| POST | `/training-courses` | Create a scheduled course | FleetAdmin |
| GET | `/training-courses` | List courses | Any |
| GET | `/training-courses/{id}` | Get one course, including seat counts | Any |
| POST | `/training-courses/{id}/cancel` | Cancel a course, cascading enrollments | FleetAdmin |
| POST | `/training-courses/{id}/enrollments` | Mariner self-request for a course seat | Mariner |
| GET | `/training-courses/{id}/enrollments` | List a course's enrollments | FleetAdmin, CrewingManager, CredentialingOfficer, PortCaptain, UnionDispatcher |
| GET | `/mariners/{id}/enrollments` | List a mariner's enrollments | Any |
| GET | `/training-enrollments/{id}` | Get one enrollment | Any |
| POST | `/training-enrollments/{id}/approve` | Approve a requested enrollment | CrewingManager |
| POST | `/training-enrollments/{id}/reject` | Reject a requested enrollment | CrewingManager |
| POST | `/training-enrollments/{id}/enroll` | Enroll an approved mariner, reserving seat and budget | FleetAdmin |
| POST | `/training-enrollments/{id}/record-completion` | Record completion or no-show | FleetAdmin |
| POST | `/training-enrollments/{id}/reimburse` | Reimburse a completed enrollment | FleetAdmin |
| POST | `/training-enrollments/{id}/cancel` | Cancel an approved or enrolled enrollment | Mariner, CrewingManager, FleetAdmin |
| GET | `/mariners/{id}/training-budgets` | List a mariner's yearly training budgets | Any |
| POST | `/union-halls` | Register a union hall | FleetAdmin |
| GET | `/union-halls` | List union halls | Any |
| GET | `/union-halls/{id}` | Get one union hall | Any |
| POST | `/union-halls/{id}/registrations` | Register a mariner with a hall | UnionDispatcher, FleetAdmin |
| GET | `/union-halls/{id}/registrations` | List a hall's registrations | Any |
| GET | `/mariners/{id}/union-registrations` | List a mariner's union registrations | Any |
| POST | `/union-halls/{id}/registrations/{registrationId}/extend-dues` | Extend dues currency | UnionDispatcher |
| POST | `/union-halls/{id}/registrations/{registrationId}/suspend` | Suspend a registration | UnionDispatcher, FleetAdmin |
| POST | `/union-halls/{id}/registrations/{registrationId}/reinstate` | Reinstate a suspended registration | UnionDispatcher, FleetAdmin |
| POST | `/_clock/set_current_utc` | Set the logical clock, running the expiry sweep | FleetAdmin |
| GET | `/_clock/current` | Read the logical clock | Any |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this table is only an identifier-to-status index.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_UNAUTHORIZED_ROLE` | 403 Forbidden |
| `ERR_FORBIDDEN_RESOURCE_ACCESS` | 403 Forbidden |
| `ERR_INVALID_REQUEST` | 400 Bad Request |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_MARINER_NOT_FOUND` | 404 Not Found |
| `ERR_VESSEL_NOT_FOUND` | 404 Not Found |
| `ERR_MANNING_SLOT_NOT_FOUND` | 404 Not Found |
| `ERR_CREDENTIAL_NOT_FOUND` | 404 Not Found |
| `ERR_SEA_SERVICE_RECORD_NOT_FOUND` | 404 Not Found |
| `ERR_MEDICAL_CERTIFICATE_NOT_FOUND` | 404 Not Found |
| `ERR_DRUG_TEST_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_COURSE_NOT_FOUND` | 404 Not Found |
| `ERR_TRAINING_ENROLLMENT_NOT_FOUND` | 404 Not Found |
| `ERR_UNION_HALL_NOT_FOUND` | 404 Not Found |
| `ERR_UNION_REGISTRATION_NOT_FOUND` | 404 Not Found |
| `ERR_ASSIGNMENT_NOT_FOUND` | 404 Not Found |
| `ERR_TRAVEL_BOOKING_NOT_FOUND` | 404 Not Found |
| `ERR_ROTATION_PLAN_NOT_FOUND` | 404 Not Found |
| `ERR_INVALID_STATE` | 409 Conflict |
| `ERR_MARINER_NOT_ACTIVE` | 409 Conflict |
| `ERR_MARINER_ACTIVATION_REQUIREMENTS_MISSING` | 409 Conflict |
| `ERR_VESSEL_NOT_ACTIVE` | 409 Conflict |
| `ERR_NO_MANNING_SLOTS` | 409 Conflict |
| `ERR_SLOT_NOT_ACTIVE` | 409 Conflict |
| `ERR_SLOT_HAS_OPEN_ASSIGNMENTS` | 409 Conflict |
| `ERR_ACTIVE_CREW_ABOARD` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_RENEWABLE` | 409 Conflict |
| `ERR_RENEWAL_NOT_PENDING` | 409 Conflict |
| `ERR_CREDENTIAL_NOT_VALID` | 409 Conflict |
| `ERR_RECORD_NOT_SUBMITTABLE` | 409 Conflict |
| `ERR_RECORD_NOT_VERIFIABLE` | 409 Conflict |
| `ERR_MEDICAL_CERT_NOT_VALID` | 409 Conflict |
| `ERR_DRUG_TEST_NOT_PENDING` | 409 Conflict |
| `ERR_COURSE_NOT_SCHEDULED` | 409 Conflict |
| `ERR_SIGN_ON_TOO_EARLY` | 409 Conflict |
| `ERR_TRAVEL_NOT_READY` | 409 Conflict |
| `ERR_RELIEF_NOT_ONBOARD` | 409 Conflict |
| `ERR_REPATRIATION_INCOMPLETE` | 409 Conflict |
| `ERR_NO_TRAVEL_LEGS` | 409 Conflict |
| `ERR_MARINER_NOT_CLEAR` | 409 Conflict |
| `ERR_RESTRICTED_WINDOW_EXCEEDED` | 409 Conflict |
| `ERR_ENDORSEMENT_MISMATCH` | 409 Conflict |
| `ERR_RANK_BELOW_MINIMUM` | 409 Conflict |
| `ERR_ENDORSEMENT_PREREQUISITE_INVALID` | 409 Conflict |
| `ERR_UPGRADE_REQUIREMENTS_NOT_MET` | 409 Conflict |
| `ERR_CHANNEL_NOT_PERMITTED` | 409 Conflict |
| `ERR_UNION_REGISTRATION_INVALID` | 409 Conflict |
| `ERR_DUES_NOT_CURRENT` | 409 Conflict |
| `ERR_NO_ACTIVE_ROTATION_WINDOW` | 409 Conflict |
| `ERR_MARINER_ASSIGNMENT_OVERLAP` | 409 Conflict |
| `ERR_HANDOVER_WINDOW_EXCEEDED` | 409 Conflict |
| `ERR_COURSE_FULL` | 409 Conflict |
| `ERR_DUPLICATE_ENROLLMENT` | 409 Conflict |
| `ERR_DUPLICATE_REGISTRATION` | 409 Conflict |
| `ERR_VESSEL_NOT_COMPLIANT` | 409 Conflict |
| `ERR_TRAINING_PRIVILEGES_SUSPENDED` | 409 Conflict |
| `ERR_SOD_VERIFY_SAME_RECORDER` | 403 Forbidden |
| `ERR_SOD_REIMBURSE_SAME_APPROVER` | 403 Forbidden |
| `ERR_TRAINING_BUDGET_EXCEEDED` | 402 Payment Required |
