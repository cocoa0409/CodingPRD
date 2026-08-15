# Sales Tax Exemption Certificates API — Product Requirements Document

## 1. Introduction

Sellers who ship into dozens of US jurisdictions carry a quiet, compounding liability: every exempt sale must be defensible, certificate by certificate, state by state, often years after the invoice is issued. Certificates expire on different clocks depending on the state's anchoring convention, drop-ship transactions drag a second party's resale documentation into the seller's audit file, and when a state auditor finally draws a sample, the desk has days — not months — to produce paperwork. The cost of getting this wrong is not the tax on one order; it is the assessment on every order the failed sample implies.

This document specifies the Sales Tax Exemption Certificates API, a multi-tenant compliance platform for running the exemption certificate desk end to end. The system collects certificates at customer onboarding, gates order fulfillment on certificate coverage, tracks validity windows per jurisdiction, verifies drop-ship resale documentation, runs proactive renewal outreach, and supports the full audit-defense loop: sampling, documentation requests with hard response deadlines, remediation work assignment, and defense packet assembly. All resources are tenant-scoped and the API is mounted under the `/tenants` prefix, with every request resolved against a single tenant boundary.

Two design commitments shape everything that follows. First, compliance posture is derived, never asserted: customer standings, tenant exposure totals, and audit posture are recomputed by the system as certificates, orders, and samples change, so a dashboard can never drift from the underlying records. Second, the desk is structured by segregation of duties — the officer who uploads a certificate may not review it, the auditor who opens a campaign may not close it, and the assignee who assesses tax may not resolve their own assessment — so every consequential transition records who performed it.

## 2. Global Specifications & System-Wide Principles

This section defines system-wide rules, contract-level response formats, and cross-cutting principles that apply to every endpoint.

### 2.1. User and Role-Based Access Control

All interactions with the API must be authenticated through a pair of mandatory HTTP headers. Each request must include `X-User-ID` to identify the acting user and `X-User-Role` to specify their operational capacity. The system recognizes exactly six roles: `TenantAdmin`, `ComplianceOfficer`, `Auditor`, `OrderClerk`, `FulfillmentClerk`, and `BillingClerk`. A request missing either header, or carrying a malformed header value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. A request whose role is not authorized for the target endpoint is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

For every role, `X-User-ID` is an opaque operator identifier and is never the `id` of any persisted entity. When `X-User-Role` is `TenantAdmin`, `ComplianceOfficer`, `Auditor`, `OrderClerk`, `FulfillmentClerk`, or `BillingClerk`, the server may record the supplied `X-User-ID` for attribution — for example as `uploaded_by_user_id` on a `CertificateVersion`, as `reviewed_by_user_id` on an `ExemptionCertificate`, as `opened_by_user_id` and `closed_by_user_id` on an `AuditCampaign`, as `assembled_by_user_id` on an `AuditDefensePacket`, or as `assigned_to_user_id` and `resolved_by_user_id` on a `RemediationAction` — and the segregation-of-duties checks in §2.9 compare these recorded identifiers against the acting `X-User-ID`. The server never compares `X-User-ID` to any entity's `id` for ownership purposes.

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

List endpoints accept two query parameters. The `limit` parameter caps the number of items returned: it defaults to 10 when omitted, accepts a minimum of 1, and is capped at a maximum of 100. The `offset` parameter controls how many items are skipped and defaults to 0. Out-of-range values are clamped to the nearest bound rather than rejected, and a non-integer value falls back to the default. Unless otherwise specified, every list endpoint returns resources sorted by their creation timestamp in ascending order. List responses carry the fields `limit`, `offset`, `total_count`, and `has_more` in the `meta` object of the response envelope.

### 2.4. The Tenant Logical Clock

Time inside a tenant is logical, not wall-clock. Every `Tenant` carries an `audit_clock_day_index`, an integer counter that starts at 0 when the tenant is created. Day index 0 corresponds to the instant 2026-08-01T00:00:00Z, and "today" for any rule evaluation is that origin instant advanced by `audit_clock_day_index` whole days. Date comparisons throughout this document — certificate expiration, audit response deadlines, outreach send schedules — are all expressed against this logical current day.

A `TenantAdmin` advances time through an admin-only clock-advance capability that accepts a `days` input and adds that many days to the tenant's `audit_clock_day_index` — an omitted or non-integer `days` is treated as 1 — returning the updated tenant with a 200 status. Advancing the clock fires three cascades, in this order, within the same call:

1. **Certificate expirations.** Every certificate in `APPROVED` status whose `expiration_date` falls strictly before the new current day transitions to `EXPIRED`; a certificate whose expiration date equals the new current day remains valid through that day. Each expiration triggers the customer- and order-level recomputation described in §3.4.
2. **Audit response deadlines.** Every audit sample in `DOC_REQUESTED` whose `doc_due_day_index` falls strictly before the new current day transitions to `EXPIRED_NO_RESPONSE`, pushing the affected customer into `FAILED_SAMPLING` standing as described in §3.8.
3. **Scheduled outreach.** Every outreach campaign in `SCHEDULED` whose `scheduled_send_day_index` is on or before the new current day executes its send, moving through `SENDING` to `DONE` within the same clock advance, as described in §3.7.

### 2.5. Common Resource Properties

Every primary resource in the system carries a standard set of system-managed fields:

- `id` (string): a server-minted unique identifier formatted as a UUID, with no type prefix.
- `created_at` (string): an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created.
- `updated_at` (string): an ISO 8601 UTC timestamp refreshed on every mutation of the resource; at creation it equals `created_at`.
- `version` (integer): a system-managed integer that starts at 1 when the resource is created and increments by exactly one on every mutation of the resource.

Recomputation of a derived field — for example a customer's `cert_standing`, an order's `covered_amount_cents`, or a tenant's `open_exposure_cents` — is a mutation of the owning resource and therefore refreshes its `updated_at` and increments its `version`, even when the recomputation was triggered indirectly by a change to a different resource.

The `OutreachNotice` resource is the single exception: it is an immutable emission record and carries only `id` and `created_at` from the common set. It has no `updated_at` field and no `version` field.

### 2.6. Tenant Scoping and Nested Resource Retrieval

Every resource in the system belongs to exactly one tenant, recorded on the resource as `tenant_id`. There is no cross-tenant visibility of any kind.

For any endpoint whose path contains multiple resource identifiers, the system validates identifiers strictly left to right. The request is rejected immediately with a 404 carrying `ERR_NOT_FOUND` at the first path identifier that does not resolve to a live record inside the tenant scope; later segments are not examined. A certificate lookup under a non-existent customer, for instance, fails on the customer segment before the certificate segment is considered.

The same tenant boundary applies to foreign keys supplied in request bodies. When a creation or action payload references another record — through fields such as `customer_id`, `certificate_id`, `exemption_reason_code`, or `drop_ship_link_id` — the referenced record must resolve within the same tenant. A reference that resolves to another tenant's data, or to nothing at all within this tenant, is rejected with a 404 carrying `ERR_CROSS_TENANT_REFERENCE`.

### 2.7. Monetary Precision, Integer Arithmetic, and Date Math

All monetary amounts are represented as integer cents — `subtotal_cents`, `unit_price_cents`, `extended_cents`, `exempt_amount_cents`, `covered_amount_cents`, `uncovered_amount_cents`, `blocked_exposure_cents`, `open_exposure_cents`, and `assessment_amount_cents` are all integer-cent values, never floats and never decimal strings. Per-line extended amounts are exact integer products of quantity and unit price. Where a calculation produces intermediate per-line values, each is floored to a whole cent before aggregation, and the final aggregate is rounded half-up to a whole cent.

Percentages are whole-number integers produced by rounding half-up. Statistical sample sizes are produced by ceiling — any fractional result rounds up to the next whole sample. Date arithmetic operates at whole-day granularity against the tenant logical clock in §2.4, adding days to ISO 8601 dates with no rounding. Threshold comparisons in this system are inclusive exactly where stated: the shipping gate in §3.5 blocks at equality, and the outreach candidacy window in §3.7 includes certificates expiring exactly on the boundary day.

### 2.8. Optimistic Concurrency Control on Parent Versions

Two write endpoints in the system carry an optimistic-concurrency requirement on a parent resource, and both use the same mechanism: when the request body includes the client's last-observed `version` of the named parent entity and that value does not equal the parent's current `version` at evaluation time, the request is rejected with `ERR_STALE_VERSION` (HTTP 412); when the field is omitted from the body, the write proceeds without an optimistic-concurrency check.

- **Certificate approval.** Approving a certificate accepts `expected_customer_version` in the request body, carrying the client's last-observed `version` of the certificate's parent `Customer`. A supplied value that mismatches — for example because another writer has since approved a different certificate for the same customer, legitimately advancing the customer's version by recomputing its standing — is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a standing it has not observed.
- **Remediation resolution.** Resolving a remediation action accepts `expected_campaign_version` in the request body, carrying the client's last-observed `version` of the parent `AuditCampaign`. A supplied value that mismatches — for example because another auditor has since initiated resampling, legitimately advancing the campaign's version — is rejected with `ERR_STALE_VERSION` (HTTP 412).

No other endpoint accepts a version field; writes not named above are processed without an optimistic-concurrency check.

### 2.9. Segregation of Duties

Three segregation-of-duties rules are enforced across the platform, each comparing the acting `X-User-ID` against an identifier recorded earlier on the resource:

1. **Reviewer versus uploader.** The officer who moves a certificate into review, approves it, or rejects it must not be the officer who uploaded the certificate's current version. The comparison is between the acting `X-User-ID` and the `uploaded_by_user_id` recorded on the `CertificateVersion` pointed to by the certificate's `current_version_id`. A violation is rejected with `ERR_SOD_REVIEWER_IS_UPLOADER` (HTTP 409).
2. **Campaign closer versus opener.** The auditor who closes an audit campaign must not be the auditor who opened it; the acting `X-User-ID` is compared to the campaign's `opened_by_user_id`. A violation is rejected with `ERR_SOD_CLOSER_IS_OPENER` (HTTP 409).
3. **Assessor versus resolver.** A remediation action of type `ASSESS_TAX` may not be resolved by the officer to whom it is assigned; the acting `X-User-ID` is compared to the action's `assigned_to_user_id`. A violation is rejected with `ERR_SOD_ASSESSOR_IS_RESOLVER` (HTTP 409).

### 2.10. Validation Priority Order

Every request is evaluated against the checks below in exactly this order, and the first failing check determines the error response. The ordering is global: a request that would fail two checks always surfaces the earlier one.

1. **Authentication context** — the `X-User-ID` and `X-User-Role` headers are present and well-formed, else `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400).
2. **Role authorization** — the supplied role is authorized for the endpoint, else `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403).
3. **Path existence** — every identifier in the path resolves to a live record inside the tenant scope, evaluated left to right, else `ERR_NOT_FOUND` (HTTP 404).
4. **Tenant scope of body references** — every foreign key in the request body resolves to a record of the same tenant, else `ERR_CROSS_TENANT_REFERENCE` (HTTP 404).
5. **State-transition validity** — the target resource is in a state that permits the requested transition, else `ERR_INVALID_STATE_TRANSITION` (HTTP 409). Transition preconditions that have no dedicated error code anywhere in this document also surface through this code.
6. **Optimistic concurrency** — on the two endpoints named in §2.8, the supplied parent-version field matches the parent's current `version`, else `ERR_STALE_VERSION` (HTTP 412).
7. **Segregation: reviewer versus uploader** — on certificate begin-review, approve, and reject, else `ERR_SOD_REVIEWER_IS_UPLOADER` (HTTP 409).
8. **Segregation: closer versus opener** — on audit campaign close, else `ERR_SOD_CLOSER_IS_OPENER` (HTTP 409).
9. **Segregation: assessor versus resolver** — on resolving an `ASSESS_TAX` remediation action, else `ERR_SOD_ASSESSOR_IS_RESOLVER` (HTTP 409).
10. **Form acceptance** — the certificate's `form_type` is accepted by the jurisdiction rule for its `ship_to_state`, else `ERR_FORM_NOT_ACCEPTED_IN_STATE` (HTTP 422).
11. **State registration** — a `state_registration_number` is present when the jurisdiction rule requires one, else `ERR_MISSING_STATE_REGISTRATION` (HTTP 422).
12. **Effective date not in the future** — at approval time the current version's `effective_date` is not later than today, else `ERR_EFFECTIVE_DATE_IN_FUTURE` (HTTP 422).
13. **Reinstatement window** — a suspended certificate is reinstated only on or before its `expiration_date`, else `ERR_CERT_EXPIRED` (HTTP 409).
14. **Outreach schedule not in the past** — the `scheduled_send_day_index` is the current day index or later, else `ERR_SCHEDULE_IN_PAST` (HTTP 422).
15. **Order non-empty** — the order has at least one line, else `ERR_ORDER_EMPTY` (HTTP 422).
16. **Onboarding complete** — the customer's `onboarding_completed_at` is set, else `ERR_ONBOARDING_INCOMPLETE` (HTTP 409).
17. **Resale certificate approved** — the drop-ship link's resale certificate is `APPROVED`, else `ERR_RESALE_CERT_NOT_APPROVED` (HTTP 409).
18. **Drop-ship state match** — required when the jurisdiction disallows out-of-state resale, else `ERR_DROP_SHIP_STATE_MISMATCH` (HTTP 422).
19. **Blocked exposure below threshold** — the customer's `blocked_exposure_cents` is below the shipping threshold, else `ERR_BLOCKED_EXPOSURE_AT_LIMIT` (HTTP 409).
20. **No unremediated failures** — every `FAILED` sample has a `RESOLVED` remediation before defense assembly, else `ERR_UNREMEDIATED_FAILURES` (HTTP 409).
21. **Packet completeness** — the defense packet's score is exactly 100 before delivery, else `ERR_PACKET_INCOMPLETE` (HTTP 409).
22. **Certificate not under audit** — a certificate may be revoked only when no non-terminal sample references it, else `ERR_CERT_UNDER_AUDIT` (HTTP 409).
23. **Outreach not yet sending** — a campaign in `SENDING` or `DONE` may not be cancelled, else `ERR_CAMPAIGN_ALREADY_SENDING` (HTTP 409).
24. **Documentation window open** — documents are received on or before `doc_due_day_index`, else `ERR_DOC_WINDOW_EXPIRED` (HTTP 409).
25. **Certificate has a version** — a certificate carries at least one uploaded version before submission, else `ERR_NO_CERT_VERSION` (HTTP 422).
26. **Reason code unique** — no duplicate `ExemptionReason.code` within the tenant, else `ERR_DUPLICATE_REASON_CODE` (HTTP 409).
27. **Jurisdiction unique** — no duplicate `JurisdictionRule.state_code` within the tenant, else `ERR_DUPLICATE_JURISDICTION` (HTTP 409).
28. **Assessment amount valid** — resolving an `ASSESS_TAX` action requires a positive `assessment_amount_cents`, else `ERR_ASSESSMENT_AMOUNT_INVALID` (HTTP 422).

Because of this ordering, a certificate submission that would fail both the form-acceptance check and the no-version check surfaces `ERR_FORM_NOT_ACCEPTED_IN_STATE`; a certificate approval with a stale customer version whose actor is also the uploader surfaces `ERR_STALE_VERSION`, not the segregation error; and an `ASSESS_TAX` resolution attempted by the assignee with a non-positive amount surfaces `ERR_SOD_ASSESSOR_IS_RESOLVER`, not `ERR_ASSESSMENT_AMOUNT_INVALID`.

## 3. Business Logic & Workflows

### 3.1. Tenant Configuration: Jurisdiction Rules and Exemption Reasons

Everything begins with the tenant. A `TenantAdmin` creates a `Tenant` with a `legal_name` and a `home_state_code` — the two-letter code of the tenant's nexus domicile, such as `CA`. Creation also accepts an optional `coverage_mode`, one of `FULL_CERT` or `LINE_LEVEL_PROPORTIONAL`, which defaults to `FULL_CERT` when omitted and pins the coverage computation of §3.5 for every order under the tenant. A new tenant starts with `audit_clock_day_index` at 0, `audit_posture` of `CLEAR`, and `open_exposure_cents` of 0. The tenant's `audit_posture` is a computed lifecycle flag that moves through `CLEAR`, `UNDER_SAMPLING`, `IN_REMEDIATION`, and `DEFENSE_ASSEMBLY` as audit campaigns progress (§3.8, §3.9), while `open_exposure_cents` is a continuously derived total defined in §3.5.

With the tenant in place, the `TenantAdmin` codifies each state's certificate policy as a `JurisdictionRule`. A rule carries the two-letter `state_code` it governs; the `accepted_form_types` list naming which of the six recognized form types — `RESALE`, `EXEMPT_ORG`, `AGRICULTURAL`, `MANUFACTURING`, `DIRECT_PAY`, and `MULTI_JURISDICTION` — that state accepts; the `validity_window_days` measuring how many days a certificate remains valid from its anchor date, where 0 means certificates for that state never expire; the `anchor_rule`, either `EFFECTIVE_DATE` or `SIGNED_DATE`, selecting which certificate date anchors the validity window; the `allows_drop_ship_resale` flag governing out-of-state resale certificates in drop-ship scenarios; the `requires_state_registration_number` flag demanding a state-issued registration number on every certificate for that state; and the `blanket_cert_allowed` flag recording whether a single blanket certificate may cover multiple ship-to states. One rule may exist per state per tenant: creating a second rule with a `state_code` already present for the tenant is rejected with `ERR_DUPLICATE_JURISDICTION` (HTTP 409). The rule list supports filtering by `state_code`. The validity-window calculation is evaluated when a certificate is approved, and re-evaluated for affected certificates whenever the governing jurisdiction rule is created or changed.

The `TenantAdmin` also maintains the tenant's `ExemptionReason` catalogue — the bridge between commercial exemption language and the downstream tax engine. Each reason has a tenant-unique short `code` (such as `RESALE`, `GOVT`, or `AGR`), a human-readable `description`, the `tax_engine_code` transmitted downstream when an order is invoiced (for example the Avalara codes `R`, `G`, or `A`), a `requires_certificate` flag, and an `allowed_form_types` list naming the subset of form types that may substantiate the reason. When `requires_certificate` is true, any order claiming the reason must be backed by a valid certificate; when false, the reason alone suffices. A duplicate `code` within the tenant is rejected with `ERR_DUPLICATE_REASON_CODE` (HTTP 409). The reason list supports filtering by `code`.

### 3.2. Customer Onboarding and the Three Standing Dimensions

A `TenantAdmin` or `ComplianceOfficer` registers a `Customer` with a tenant-supplied `external_ref`, the customer's `legal_name`, a `primary_ship_to_state` used as the default destination when an order line omits one, and a default `exemption_reason_code` applied to orders when a certificate is silent. Creation begins onboarding: the new customer's `onboarding_completed_at` is null, and orders cannot be submitted for the customer until a `ComplianceOfficer` marks onboarding complete, which stamps `onboarding_completed_at` with the current timestamp and increments the customer's `version`. Marking an already-onboarded customer complete succeeds again, re-stamping the timestamp. A submission attempt before that point is rejected with `ERR_ONBOARDING_INCOMPLETE` (HTTP 409).

Every customer carries three independent, parallel standing dimensions. Transitions on one dimension never preclude or imply transitions on the others; all three are recomputed continuously as certificates, samples, and remediation actions change. The customer list endpoint supports filtering by `cert_standing`, `collection_standing`, and `audit_standing` independently.

**Certificate standing** (`cert_standing`) tracks coverage of the customer's shipping footprint — the distinct set of states the customer ships into, anchored by `primary_ship_to_state` and extended by the `ship_to_state` of the customer's orders. A customer is created at `MISSING`. When the customer's first certificate reaches `APPROVED` while at least one footprint state still lacks an approved certificate, standing moves `MISSING` → `PARTIAL`; the transition recomputes the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`. When every footprint state has at least one approved, unexpired certificate whose `ship_to_state` covers it, standing moves `PARTIAL` → `COMPLIANT`, again recomputing `blocked_exposure_cents`. Regression is symmetric: when the customer's last approved certificate leaves `APPROVED` — through expiration, revocation, or supersession — standing falls `PARTIAL` → `MISSING`, and when some previously covered state loses coverage while others remain covered, standing falls `COMPLIANT` → `PARTIAL`; both regressions recompute `blocked_exposure_cents`. Because the standing is recomputed from current records rather than walked step by step, a single approval covering every footprint state moves a customer directly `MISSING` → `COMPLIANT`.

**Collection standing** (`collection_standing`) tracks expiration proximity. A customer starts at `CURRENT`. When any approved certificate for the customer comes within the renewal window — that is, the number of days from the current logical day to the certificate's `expiration_date` is forty-five or fewer, a certificate expiring exactly forty-five days out included — standing moves `CURRENT` → `RENEWAL_DUE`. From `RENEWAL_DUE`, if a previously approved certificate transitions to `EXPIRED` while no approved certificate — superseding or otherwise — covers the expired certificate's `ship_to_state`, standing moves to `LAPSED`; if instead a renewal certificate is approved before the old certificate's `expiration_date`, standing returns to `CURRENT`. A `LAPSED` customer returns to `CURRENT` when a newly approved certificate restores coverage for the lapsed state. The outreach machinery in §3.7 also pushes notified customers into `RENEWAL_DUE`.

**Audit standing** (`audit_standing`) tracks sampling exposure. A customer starts at `NOT_UNDER_AUDIT` and moves to `SAMPLED` the moment an audit sample row naming the customer is created during campaign sampling. When any sample for the customer reaches `FAILED` or `EXPIRED_NO_RESPONSE`, standing moves `SAMPLED` → `FAILED_SAMPLING` and the tenant's `audit_posture` is recomputed. When every `FAILED` sample for the customer has at least one `RESOLVED` remediation action and no sample for the customer sits in `EXPIRED_NO_RESPONSE`, standing moves `FAILED_SAMPLING` → `REMEDIATED`, again recomputing the tenant's `audit_posture`; a customer with an `EXPIRED_NO_RESPONSE` sample remains in `FAILED_SAMPLING` regardless of remediations.

Finally, the customer carries `blocked_exposure_cents`, a derived total defined precisely in §3.5: the sum of `uncovered_amount_cents` across the customer's orders currently sitting in `HELD_FOR_CERT`. It starts at zero and is recomputed on every event that changes certificate coverage or order state.

### 3.3. Certificate Intake, Review, and the Approval Cascade

A `ComplianceOfficer` collects a certificate by creating an `ExemptionCertificate` under a customer. The intake payload names the `ship_to_state` the certificate exempts shipments into, the `form_type` (one of `RESALE`, `EXEMPT_ORG`, `AGRICULTURAL`, `MANUFACTURING`, `DIRECT_PAY`, `MULTI_JURISDICTION`), the `exemption_reason_code` referencing the tenant's reason catalogue, the `state_registration_number` issued by the state, the buyer's `signed_date`, and the `effective_date` on which the certificate takes effect. An optional `supersedes_certificate_id` marks the new certificate as the renewal of an existing one (§3.4). A new certificate starts in `DRAFT`. The certificate list for a customer supports filtering by `status` and `ship_to_state`.

A certificate is a versioned document. Each upload against a certificate creates a `CertificateVersion` carrying the `file_uri` of the uploaded document image plus its own `form_type`, `signed_date`, and `effective_date`, so corrections over time are tracked per version rather than overwriting the certificate header. The server stamps each version with the uploader's `X-User-ID` as `uploaded_by_user_id` — the value the segregation check in §2.9 compares against — and assigns a `version_index` that starts at 1 for the first version and increases monotonically per certificate. Uploading a version — permitted against a certificate in any status — points the certificate's `current_version_id` at the new version and increments the certificate's `version` by one. Uploading a new version against a certificate in `REJECTED` additionally re-opens the certificate to `DRAFT`, closing the rejection loop.

**Submission.** A `ComplianceOfficer` submits a `DRAFT` certificate for review. Submission evaluates its checks in the global order of §2.10: the certificate must be in `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`); then the certificate's `form_type` must appear in the `accepted_form_types` of the jurisdiction rule governing its `ship_to_state` (else `ERR_FORM_NOT_ACCEPTED_IN_STATE`, HTTP 422); then, when that rule's `requires_state_registration_number` is true, the certificate's `state_registration_number` must be non-empty (else `ERR_MISSING_STATE_REGISTRATION`, HTTP 422); and finally at least one `CertificateVersion` must have been uploaded, so that `current_version_id` is set (else `ERR_NO_CERT_VERSION`, HTTP 422). A certificate with both an unaccepted form type and no uploaded version therefore surfaces `ERR_FORM_NOT_ACCEPTED_IN_STATE`. Successful submission moves the certificate `DRAFT` → `SUBMITTED`, increments the certificate's `version`, and refreshes the tenant's `updated_at`.

**Review.** A `ComplianceOfficer` begins review, moving the certificate `SUBMITTED` → `UNDER_REVIEW`; the segregation rule of §2.9 applies, so an actor whose `X-User-ID` equals the current version's `uploaded_by_user_id` is rejected with `ERR_SOD_REVIEWER_IS_UPLOADER`. From `UNDER_REVIEW` the officer either rejects or approves. Rejection moves the certificate to `REJECTED`, records the actor as `reviewed_by_user_id`, stamps `review_decision_at` with the decision timestamp, applies the same segregation rule, and increments the certificate's `version`.

Approval is the cascade-heavy path. Approving a certificate moves it `UNDER_REVIEW` → `APPROVED` and enforces its checks in global order: the state check first; then the optimistic-concurrency check of §2.8, which, when `expected_customer_version` is supplied, requires it to match the customer's current `version` and rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412); then the segregation rule, rejecting an approver who uploaded the current version with `ERR_SOD_REVIEWER_IS_UPLOADER`; then a consistency check that the current version's `form_type` matches the certificate's declared `form_type`, failing as an invalid transition when they diverge; and finally the temporal check that the current version's `effective_date` is on or before today — today being the tenant logical clock of §2.4 — rejecting a future-dated certificate with `ERR_EFFECTIVE_DATE_IN_FUTURE` (HTTP 422).

On approval the system records `reviewed_by_user_id` and stamps `review_decision_at` with the decision timestamp, then computes the certificate's `expiration_date` per the jurisdiction's validity rule: the anchor date is the certificate's `effective_date` when the governing rule's `anchor_rule` is `EFFECTIVE_DATE`, and the certificate's `signed_date` when the `anchor_rule` is `SIGNED_DATE` — the two anchor variants can legitimately produce different expiration dates for the same certificate, and the rule alone decides which applies. When the rule's `validity_window_days` is 0 the certificate never expires and `expiration_date` is null; otherwise `expiration_date` is the anchor date plus `validity_window_days` days, computed as whole-day date arithmetic with no rounding.

The approval then propagates outward. The customer's `cert_standing` and `collection_standing` are recomputed per §3.2 — the first approved certificate lifts a `MISSING` customer to `PARTIAL`, and a renewal approved before the old certificate expires restores `RENEWAL_DUE` to `CURRENT` — and the customer's `version` increments. For every order of this customer sitting in `HELD_FOR_CERT` whose `ship_to_state` matches the certificate's `ship_to_state`, the system recomputes `covered_amount_cents` under §3.5; any order whose `uncovered_amount_cents` thereby falls to zero is released, transitioning `HELD_FOR_CERT` → `READY_TO_SHIP` with its own `version` increment, and the released exposure comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`. The tenant's `open_exposure_cents` is then recomputed across the order population and the tenant's `version` increments.

### 3.4. Certificate Renewal, Suspension, Expiration, and Revocation

An approved certificate leaves `APPROVED` along four distinct paths, and each path unwinds through customers and orders differently. `REVOKED` and `SUPERSEDED` are terminal; `EXPIRED` certificates are never reinstated; `SUSPENDED` is the only state that returns to `APPROVED`.

**Suspension and reinstatement.** A `ComplianceOfficer` may suspend an `APPROVED` certificate, moving it `APPROVED` → `SUSPENDED`. Suspension immediately recomputes the customer's `cert_standing`, which may drop `COMPLIANT` → `PARTIAL` when the suspended certificate was covering a state nothing else covers. Every order of the customer in `READY_TO_SHIP` that depended on the suspended certificate has its `covered_amount_cents` recomputed under §3.5; when the recomputation leaves `uncovered_amount_cents` above zero the order is pulled back, transitioning `READY_TO_SHIP` → `HELD_FOR_CERT` and adding the newly uncovered amount onto both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`. Reinstatement moves a `SUSPENDED` certificate back to `APPROVED`, but only while today is on or before the certificate's `expiration_date`; a reinstatement attempted after expiry is rejected with `ERR_CERT_EXPIRED` (HTTP 409), while a certificate whose `expiration_date` is null may be reinstated at any time. A successful reinstatement applies the approval cascade symmetrically: standings recompute upward and held orders whose coverage is restored are released back to `READY_TO_SHIP`.

**Expiration.** When a clock advance moves the current day strictly past an approved certificate's `expiration_date`, the certificate transitions `APPROVED` → `EXPIRED` automatically. Unless a superseding approved certificate is already in place, the customer's `collection_standing` falls to `LAPSED`; `cert_standing` is recomputed; and dependent orders in `READY_TO_SHIP` that lose coverage transition to `HELD_FOR_CERT` whenever their recomputed `uncovered_amount_cents` rises above zero, with the corresponding exposure increments.

**Supersession.** Renewal is modeled as a new certificate created with `supersedes_certificate_id` pointing at the certificate being replaced — a self-referential link on the certificate entity. The renewal's `ship_to_state` must equal the superseded certificate's `ship_to_state` — the equality is enforced at the moment the renewal is approved, failing as an invalid transition when the states diverge — and the renewal must reach `APPROVED` through the normal review flow; at the moment the renewal is approved, a predecessor still in `APPROVED` transitions `APPROVED` → `SUPERSEDED` and its `superseded_by_certificate_id` is set to the renewal's id, while a predecessor that has already left `APPROVED` is left unchanged. Because the renewal is approved in the same flow, the customer's coverage never lapses and `collection_standing` stays `CURRENT`.

**Revocation.** A `ComplianceOfficer` may revoke an `APPROVED` certificate, but only when no audit sample in a non-terminal outcome references it — a certificate under active audit is frozen in place, and the revocation is rejected with `ERR_CERT_UNDER_AUDIT` (HTTP 409). Successful revocation moves the certificate to `REVOKED`, recomputes the customer's `cert_standing`, and recomputes dependent orders, re-gating any `READY_TO_SHIP` order whose coverage fell short.

### 3.5. Order Capture, Exemption Coverage, and the Shipping Gate

An `OrderClerk` captures an `Order` under a customer, providing an `order_ref` kept unique per tenant by caller convention — the server records the supplied value and performs no duplicate check — the destination `ship_to_state` that drives certificate lookup, the `exemption_reason_code` the order claims, and — for drop-ship business — an optional `drop_ship_link_id`. A new order starts in `DRAFT` with `subtotal_cents` at 0. The clerk then adds lines — a line may be added while the order is in any status: each `OrderLine` is recorded against its parent order as `order_id` and carries a `sku`, a `quantity`, a `unit_price_cents`, and the `is_exempt_claimed` toggle; a line whose toggle is false is always taxable. The line's `extended_cents` is the exact integer product of `quantity` and `unit_price_cents`, and every line addition recomputes the order's `subtotal_cents` as the sum of `extended_cents` across all lines and increments the order's `version`. The order list supports filtering by `customer_id` and `status`.

**Submission and the coverage computation.** Submitting an order validates, in global priority order: the order must be in `DRAFT` (else `ERR_INVALID_STATE_TRANSITION`); the order must have at least one line (else `ERR_ORDER_EMPTY`, HTTP 422) — this check precedes the onboarding check, so an empty order on a customer with incomplete onboarding surfaces `ERR_ORDER_EMPTY`; the customer's `onboarding_completed_at` must be set (else `ERR_ONBOARDING_INCOMPLETE`, HTTP 409); and either the claimed exemption reason's `requires_certificate` flag must be true or the order's computed `exempt_amount_cents` must be zero, failing as an invalid transition otherwise.

A successful submission computes three amounts. The `exempt_amount_cents` is the sum of `extended_cents` across the lines whose `is_exempt_claimed` is true. The system then looks up an approved certificate held by the order's customer, covering the order's `ship_to_state`, and carrying the claimed `exemption_reason_code`. What that certificate covers depends on the tenant's configured coverage mode, `coverage_mode`, which pins exactly one of two variants for every order:

- Under `FULL_CERT`, coverage is binary per certificate: when the lookup finds such a certificate, `covered_amount_cents` equals the full `exempt_amount_cents`; when no certificate matches, `covered_amount_cents` is 0.
- Under `LINE_LEVEL_PROPORTIONAL`, coverage is computed line by line. When no certificate matches, the covered amount is 0. When a certificate matches, the system sums `extended_cents` across the exempt-claimed lines whose `sku` begins with the prefix `EX`; if that matching sum is greater than zero it becomes `covered_amount_cents`. If no line matches the prefix, the covered amount falls back to the default proportion of one half of `exempt_amount_cents`, rounded up to the next whole cent when the exempt amount is odd. All arithmetic runs in integer cents, intermediate per-line values floored, the final sum rounded half-up — so identical inputs produce different covered amounts under the two modes, and the tenant's mode alone decides which is stored.

The `uncovered_amount_cents` is the exempt amount minus the covered amount. The order passes through `SUBMITTED` momentarily and the system routes it on the coverage result: when the covered amount falls short of the exempt amount the order lands in `HELD_FOR_CERT`, and its `uncovered_amount_cents` is added to both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`; when coverage is complete the order lands in `READY_TO_SHIP`. Both customer and tenant exposure totals are derived sums — the customer's `blocked_exposure_cents` is always the sum of `uncovered_amount_cents` across exactly its `HELD_FOR_CERT` orders, while the tenant's `open_exposure_cents` is the sum of `uncovered_amount_cents` across all non-terminal orders in the tenant, an order being non-terminal until it reaches `CANCELLED` or `INVOICED` — and every later event that moves an order into or out of `HELD_FOR_CERT` restates both totals accordingly.

**The shipping gate.** A `FulfillmentClerk` ships an order, moving it `READY_TO_SHIP` → `SHIPPED`. Two conditions guard the gate. The order must genuinely be in `READY_TO_SHIP` — which by construction means its covered amount equals its exempt amount; a ship attempt in any other state is rejected with `ERR_INVALID_STATE_TRANSITION`. And the customer's total blocked exposure must sit below the block threshold of ten million cents ($100,000.00): when the customer's `blocked_exposure_cents` is equal to or greater than $100,000.00 the ship is rejected with `ERR_BLOCKED_EXPOSURE_AT_LIMIT` (HTTP 409). The comparison is inclusive at the threshold — a customer at exactly $100,000.00 of blocked exposure cannot ship, while a customer at $99,999.99 can.

**Invoicing and cancellation.** A `BillingClerk` invoices a `SHIPPED` order, moving it `SHIPPED` → `INVOICED`; at that point the order's `applied_tax_engine_code` is resolved from the claimed reason's `tax_engine_code` for transmission to the downstream tax engine, remaining null when no valid reason was resolved. An `OrderClerk` may cancel an order from `DRAFT` or from `HELD_FOR_CERT`. Cancelling a held order releases its blocked exposure: the order's `uncovered_amount_cents` comes off both the customer's `blocked_exposure_cents` and the tenant's `open_exposure_cents`. Cancellation from `DRAFT` touches no exposure totals. `CANCELLED` and `INVOICED` are terminal.

### 3.6. Drop-Ship Resale Verification

Drop-ship transactions put the tenant in the middle of someone else's sale: the retailer sold to the end consumer, and the tenant ships on the retailer's resale certificate. A `ComplianceOfficer` registers the arrangement as a `DropShipLink` naming the `retailer_customer_id`, the end-consumer `ship_to_state`, and the `resale_certificate_id` the retailer provided. A new link starts in `PENDING_VERIFICATION`, and orders in the drop-ship flow carry the link's id as their `drop_ship_link_id`.

Verification enforces two checks in order. First, the referenced resale certificate must be in `APPROVED` status; verifying against a certificate in any other status is rejected with `ERR_RESALE_CERT_NOT_APPROVED` (HTTP 409). Second, state alignment depends on the jurisdiction rule for the link's `ship_to_state`: when that rule's `allows_drop_ship_resale` is false, the resale certificate's own `ship_to_state` must equal the link's `ship_to_state`, and a mismatch is rejected with `ERR_DROP_SHIP_STATE_MISMATCH` (HTTP 422); when the rule's `allows_drop_ship_resale` is true, an out-of-state resale certificate is accepted as-is. When no jurisdiction rule exists for the link's `ship_to_state`, out-of-state resale is treated as disallowed, so the state match is required. A successful verification moves the link `PENDING_VERIFICATION` → `VERIFIED` and computes its `is_out_of_state_resale_accepted` flag from the governing rule's `allows_drop_ship_resale` value. A `ComplianceOfficer` may instead reject the link, moving it to `REJECTED`. Both `VERIFIED` and `REJECTED` are terminal.

### 3.7. Renewal Outreach Campaigns

Collection standing tells the desk which customers are drifting toward lapse; outreach campaigns act on it. A `ComplianceOfficer` creates an `OutreachCampaign` with a `name`, an optional `target_state_filter` list — an empty filter means all states — a `days_before_expiration` window, and the `scheduled_send_day_index` on which notices should go out. A new campaign starts in `DRAFT` with `sent_count` at 0.

Scheduling the campaign moves it `DRAFT` → `SCHEDULED` and validates the timing: the `scheduled_send_day_index` must be the tenant's current day index or a later day — a send day in the past is rejected with `ERR_SCHEDULE_IN_PAST` (HTTP 422) — and `days_before_expiration` must be at least 1, failing as an invalid transition otherwise.

Execution is deferred to the clock. When a clock advance brings the tenant's `audit_clock_day_index` to a `SCHEDULED` campaign's `scheduled_send_day_index` or past it, the campaign moves `SCHEDULED` → `SENDING` and the system selects candidate certificates: certificates in `APPROVED` status, with a non-null `expiration_date`, whose remaining lifetime — the number of days from the current day to the `expiration_date` — is less than or equal to the campaign's `days_before_expiration`, and whose `ship_to_state` appears in `target_state_filter` when the filter is non-empty. The window boundary is inclusive: a certificate expiring exactly `days_before_expiration` days from the current day is selected. Candidates are ordered deterministically by the owning customer's `created_at` ascending and then the certificate's `created_at` ascending, with no id-based tie-break. For each candidate, in that order, the system emits an `OutreachNotice` — copying the campaign's `scheduled_send_day_index` onto the notice and stamping `sent_at_day_index` with the current day index — and increments the campaign's `sent_count` by one per notice. Every notified customer's `collection_standing` moves to `RENEWAL_DUE`. Once all notices for the campaign are created, the campaign moves `SENDING` → `DONE` within the same clock advance. `DONE` and `CANCELLED` are terminal.

Notices are immutable emission records: an `OutreachNotice` carries its `campaign_id`, `tenant_id`, `customer_id`, and `certificate_id` alongside the send indices, and per §2.5 exposes only `id` and `created_at` from the common fields — it has neither `updated_at` nor `version`. The campaign's notice list is available for review.

A `ComplianceOfficer` may cancel a campaign from `DRAFT` at any time. A `SCHEDULED` campaign may be cancelled only while the current day remains strictly earlier than its `scheduled_send_day_index`. Cancellation of a campaign already in `SENDING` or `DONE` is rejected with `ERR_CAMPAIGN_ALREADY_SENDING` (HTTP 409).

### 3.8. Audit Campaigns: Sampling, Fieldwork, and the Response Window

When a state auditor comes calling, an `Auditor` opens the tenant's side of the file as an `AuditCampaign`. Creation captures the campaign `name`, an optional `population_state_filter` list limiting the sampling population by certificate state — an empty filter means all states — and the `sampling_method`, either `STATISTICAL` or `FIXED_FLOOR`. The two methods take different parameters: a `STATISTICAL` campaign takes a `target_confidence_pct` of 90, 95, or 99, while a `FIXED_FLOOR` campaign takes a `floor_sample_size` of at least 1. A new campaign starts in `DRAFT`.

Opening the campaign moves it `DRAFT` → `SAMPLING`. The configuration must be coherent at open time: the `sampling_method` must be one of the two supported values, a `STATISTICAL` campaign must carry a `target_confidence_pct` of 90, 95, or 99, and a `FIXED_FLOOR` campaign must carry a `floor_sample_size` of at least 1; an incoherent configuration is rejected as an invalid transition with `ERR_INVALID_STATE_TRANSITION`. Opening records the acting auditor as `opened_by_user_id`, moves the tenant's `audit_posture` to `UNDER_SAMPLING`, increments the versions of both campaign and tenant, and computes the campaign's `planned_sample_size` against the population — the count of the tenant's `APPROVED` certificates, restricted to certificates whose state appears in `population_state_filter` when the filter is non-empty. The two methods compute the plan differently, and the method alone decides which applies:

- Under `STATISTICAL`, the planned size is the population count multiplied by the confidence multiplier, rounded up to the next whole sample, with a hard minimum of one sample. The confidence multiplier is ten percent (0.10) for a target of 90, fifteen percent (0.15) for 95, and twenty-five percent (0.25) for 99. A population of seven certificates at 90 confidence therefore yields a product of seven-tenths, which rounds up to exactly one sample.
- Under `FIXED_FLOOR`, the planned size is the larger of the campaign's `floor_sample_size` and the smaller of the population count and five. The floor wins even when it exceeds the population: a population of three certificates with a `floor_sample_size` of ten yields a plan of ten samples.

Drawing the sample moves the campaign `SAMPLING` → `FIELDWORK`. The system creates exactly `planned_sample_size` `AuditSample` rows in `PENDING` outcome, each referencing its `certificate_id`, the owning `customer_id` denormalized for selection, and the tenant's `audit_clock_day_index` at sampling time as `sampled_at_day_index`. The rows reference the population as it stands at draw time; when the plan exceeds the population, the population is cycled in creation order until the plan is filled, so a certificate may be referenced by more than one row. Every customer named by a new sample moves to `SAMPLED` audit standing, and the campaign's `version` increments. The campaign's sample list supports filtering by `outcome`.

Each sample then runs a documentation cycle with a hard deadline. An `Auditor` requests documentation, moving the sample `PENDING` → `DOC_REQUESTED` and setting `doc_due_day_index` to the current day index plus ten — a ten-day response window, the sample's `doc_due_day_index` being defined as `sampled_at_day_index` plus ten days and re-stamped to the current day plus ten whenever documentation is requested. A `ComplianceOfficer` records receipt of the paperwork, moving the sample `DOC_REQUESTED` → `DOC_RECEIVED`, but only while the current day is on or before `doc_due_day_index`; a receipt attempted after the deadline is rejected with `ERR_DOC_WINDOW_EXPIRED` (HTTP 409), and when a clock advance carries the current day past the deadline, the sample instead transitions automatically to `EXPIRED_NO_RESPONSE` and the customer's audit standing falls to `FAILED_SAMPLING`.

From `DOC_RECEIVED`, an `Auditor` has three exits. Requesting rework loops the sample back `DOC_RECEIVED` → `DOC_REQUESTED` and re-extends `doc_due_day_index` to the current day plus ten. Passing moves the sample to `PASSED`. Failing moves the sample to `FAILED`, records the auditor-supplied `failure_reason` on the sample, drops the customer to `FAILED_SAMPLING`, and automatically creates a `RemediationAction` in `OPEN` status with `action_type` `COLLECT_NEW_CERT` and `assigned_to_user_id` set to `system`. From either `DOC_REQUESTED` or `DOC_RECEIVED`, an `Auditor` may instead waive the sample, moving it to `WAIVED`. `PASSED`, `FAILED`, `WAIVED`, and `EXPIRED_NO_RESPONSE` are the sample's terminal outcomes.

When every sample in the campaign has reached a terminal outcome, the campaign transitions automatically `FIELDWORK` → `REMEDIATION`, and the tenant's `audit_posture` moves to `IN_REMEDIATION`.

### 3.9. Remediation, Defense Packets, and Campaign Closure

Remediation is where failed samples get fixed. Beyond the `COLLECT_NEW_CERT` action created automatically on sample failure, an `Auditor` may create a `RemediationAction` under any sample — the new action's `sample_id` ties it to that sample — choosing an `action_type` of `ASSESS_TAX`, `OBTAIN_LETTER`, or `WAIVE_SAMPLE`, naming the compliance officer responsible as `assigned_to_user_id`, and — for `ASSESS_TAX` — supplying the `assessment_amount_cents` to be assessed. Every action also carries the sample's `customer_id`, denormalized onto the action. Manual actions start in `OPEN`. The sample's remediation list is available for review.

Work on an action follows a cyclic flow with an escalation branch. The assigned `ComplianceOfficer` begins work, moving the action `OPEN` → `IN_PROGRESS`; only the assignee may begin — an actor whose `X-User-ID` differs from `assigned_to_user_id` fails as an invalid transition. From `IN_PROGRESS` the action may be escalated to `ESCALATED`, and beginning work again returns an `ESCALATED` action to `IN_PROGRESS`, with the same assignee-only rule. `RESOLVED` is the action's terminal state, reached only from `IN_PROGRESS`, and resolution is the second optimistic-concurrency point in the system: per §2.8 the request must carry `expected_campaign_version` matching the parent campaign's current `version`, with a mismatch rejected as `ERR_STALE_VERSION` (HTTP 412).

Resolution then applies type-specific gates in global priority order. For an `ASSESS_TAX` action, the segregation rule fires first: the resolver must differ from `assigned_to_user_id`, else `ERR_SOD_ASSESSOR_IS_RESOLVER` (HTTP 409) — an assessor may never close their own assessment. Only then is the amount checked: `assessment_amount_cents` must be greater than zero, else `ERR_ASSESSMENT_AMOUNT_INVALID` (HTTP 422). For a `COLLECT_NEW_CERT` action, a new certificate for the same customer and state must have reached `APPROVED`; without it the resolve fails as an invalid transition. A successful resolution records the actor as `resolved_by_user_id` and increments the versions of both the action and the parent campaign. When the resolution leaves every `FAILED` sample for the customer with at least one `RESOLVED` action, the customer's audit standing moves `FAILED_SAMPLING` → `REMEDIATED` and the tenant's `audit_posture` is recomputed.

Two exits lead out of `REMEDIATION`. If the desk wants a second look, an `Auditor` resamples: the campaign moves `REMEDIATION` → `FIELDWORK`, requiring at least one remediation action in `RESOLVED` status — failing as an invalid transition otherwise — and the system creates fresh `AuditSample` rows for the previously failed certificates, exactly one fresh `PENDING` sample per distinct previously-failed certificate, leaving the campaign's `planned_sample_size` unchanged and the tenant's `audit_posture` at `IN_REMEDIATION`. Otherwise the `Auditor` begins defense assembly, moving the campaign `REMEDIATION` → `DEFENSE_ASSEMBLY`, which is permitted only when every `FAILED` sample in the campaign has at least one `RESOLVED` remediation action; otherwise the request is rejected with `ERR_UNREMEDIATED_FAILURES` (HTTP 409). The transition moves the tenant's `audit_posture` to `DEFENSE_ASSEMBLY` and creates the campaign's `AuditDefensePacket` in `DRAFT`. The packet is one-to-one with its campaign: retrieving it returns an array containing zero or one element.

Assembling the packet requires the campaign to be in `DEFENSE_ASSEMBLY` — an assemble attempt in any other campaign state fails as an invalid transition — and moves the packet `DRAFT` → `ASSEMBLED` while computing its three derived fields. The `included_certificate_ids` list holds the certificates referenced by samples whose outcome is `PASSED` or `WAIVED`, sorted by certificate `created_at` ascending. The `missing_certificate_ids` list holds the certificates referenced by `FAILED` samples that still lack a `RESOLVED` remediation, sorted by certificate `created_at` ascending as well. The `completeness_score_pct` is one hundred times the number of included certificates divided by the combined count of included plus missing certificates, rounded half-up to a whole percent; when both lists are empty the score is 0. The assembling auditor is recorded as `assembled_by_user_id`. Delivery moves the packet `ASSEMBLED` → `DELIVERED` and demands a complete file: a packet whose `completeness_score_pct` is anything short of exactly 100 is rejected with `ERR_PACKET_INCOMPLETE` (HTTP 409). `DELIVERED` is the packet's terminal state.

Closing the campaign moves it `DEFENSE_ASSEMBLY` → `CLOSED`. The defense packet must already be `DELIVERED` — closing with an undelivered packet fails as an invalid transition — and the segregation rule of §2.9 applies: the acting auditor's `X-User-ID` must differ from the campaign's `opened_by_user_id`, else `ERR_SOD_CLOSER_IS_OPENER` (HTTP 409). A successful close records the actor as `closed_by_user_id` and returns the tenant's `audit_posture` to `CLEAR`. A campaign may instead be cancelled: from `DRAFT` cancellation carries no further effect, while cancelling from `SAMPLING` — before any sample has been drawn — also returns the tenant's `audit_posture` to `CLEAR`. `CLOSED` and `CANCELLED` are terminal.

## 4. Endpoint Definitions

Operations that create a new resource return `201 Created`. Operations that modify an existing resource — including every state-transition action and the clock-advance capability — return `200 OK`. All responses use the envelope of §2.2, list endpoints paginate per §2.3, and authorization failures surface per §2.1. A request to an undefined path, or to a defined path with an unsupported method, surfaces `ERR_NOT_FOUND` (HTTP 404) in the standard error envelope.

| Method | Path | Description | Authorized Role(s) |
| ------ | ---- | ----------- | ------------------ |
| POST | `/tenants` | Create a Tenant | TenantAdmin |
| GET | `/tenants/{tid}` | Get a Tenant | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk, FulfillmentClerk, BillingClerk |
| POST | `/tenants/{tid}/_clock/advance_day` | Advance the tenant's logical clock by a number of days | TenantAdmin |
| POST | `/tenants/{tid}/jurisdiction_rules` | Create a JurisdictionRule | TenantAdmin |
| GET | `/tenants/{tid}/jurisdiction_rules` | List JurisdictionRules | TenantAdmin, ComplianceOfficer, Auditor |
| GET | `/tenants/{tid}/jurisdiction_rules/{id}` | Get one JurisdictionRule | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/exemption_reasons` | Create an ExemptionReason | TenantAdmin |
| GET | `/tenants/{tid}/exemption_reasons` | List ExemptionReasons | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk |
| POST | `/tenants/{tid}/customers` | Create a Customer and begin onboarding | TenantAdmin, ComplianceOfficer |
| GET | `/tenants/{tid}/customers` | List Customers | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk |
| GET | `/tenants/{tid}/customers/{id}` | Get a Customer | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk, FulfillmentClerk, BillingClerk |
| POST | `/tenants/{tid}/customers/{id}/complete_onboarding` | Mark customer onboarding complete | ComplianceOfficer |
| POST | `/tenants/{tid}/customers/{cid}/certificates` | Create an ExemptionCertificate in DRAFT, optionally superseding an existing certificate | ComplianceOfficer |
| GET | `/tenants/{tid}/customers/{cid}/certificates` | List certificates for a customer | TenantAdmin, ComplianceOfficer, Auditor |
| GET | `/tenants/{tid}/certificates/{id}` | Get a certificate | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/certificates/{id}/versions` | Upload a new CertificateVersion; re-opens a REJECTED certificate to DRAFT | ComplianceOfficer |
| GET | `/tenants/{tid}/certificates/{id}/versions` | List versions of a certificate | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/certificates/{id}/submit` | Submit a certificate for review | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/begin_review` | Move a certificate to UNDER_REVIEW | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/approve` | Approve a certificate; requires the parent customer's version | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/reject` | Reject a certificate | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/suspend` | Suspend an APPROVED certificate | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/reinstate` | Reinstate a SUSPENDED certificate | ComplianceOfficer |
| POST | `/tenants/{tid}/certificates/{id}/revoke` | Revoke an APPROVED certificate | ComplianceOfficer |
| POST | `/tenants/{tid}/customers/{cid}/orders` | Create an Order in DRAFT | OrderClerk |
| GET | `/tenants/{tid}/orders` | List Orders | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk |
| GET | `/tenants/{tid}/orders/{id}` | Get an Order | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk, FulfillmentClerk, BillingClerk |
| POST | `/tenants/{tid}/orders/{id}/lines` | Add an OrderLine | OrderClerk |
| GET | `/tenants/{tid}/orders/{id}/lines` | List lines for an order | TenantAdmin, ComplianceOfficer, Auditor, OrderClerk, FulfillmentClerk, BillingClerk |
| POST | `/tenants/{tid}/orders/{id}/submit` | Submit an Order; the system routes to HELD_FOR_CERT or READY_TO_SHIP | OrderClerk |
| POST | `/tenants/{tid}/orders/{id}/ship` | Ship a READY_TO_SHIP order; blocked-exposure gate enforced | FulfillmentClerk |
| POST | `/tenants/{tid}/orders/{id}/invoice` | Invoice a SHIPPED order | BillingClerk |
| POST | `/tenants/{tid}/orders/{id}/cancel` | Cancel a DRAFT or HELD_FOR_CERT order | OrderClerk |
| POST | `/tenants/{tid}/drop_ship_links` | Create a DropShipLink | ComplianceOfficer |
| GET | `/tenants/{tid}/drop_ship_links/{id}` | Get a DropShipLink | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/drop_ship_links/{id}/verify` | Verify a DropShipLink | ComplianceOfficer |
| POST | `/tenants/{tid}/drop_ship_links/{id}/reject` | Reject a DropShipLink | ComplianceOfficer |
| POST | `/tenants/{tid}/audit_campaigns` | Create an AuditCampaign in DRAFT | Auditor |
| GET | `/tenants/{tid}/audit_campaigns/{id}` | Get an AuditCampaign | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/open` | Open a campaign; computes the planned sample size | Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/sample` | Generate AuditSample rows and enter FIELDWORK | Auditor |
| GET | `/tenants/{tid}/audit_campaigns/{id}/samples` | List samples of a campaign | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/resample` | Re-enter FIELDWORK with fresh samples for previously failed certificates | Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/begin_defense_assembly` | Move a campaign to DEFENSE_ASSEMBLY and create its defense packet | Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/close` | Close a campaign; closer must differ from opener | Auditor |
| POST | `/tenants/{tid}/audit_campaigns/{id}/cancel` | Cancel a DRAFT or SAMPLING campaign | Auditor |
| GET | `/tenants/{tid}/audit_samples/{id}` | Get an AuditSample | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/audit_samples/{id}/request_docs` | Request documentation for a sample; sets the ten-day deadline | Auditor |
| POST | `/tenants/{tid}/audit_samples/{id}/receive_docs` | Record receipt of documentation within the deadline | ComplianceOfficer |
| POST | `/tenants/{tid}/audit_samples/{id}/request_rework` | Return a received sample to DOC_REQUESTED with a re-extended deadline | Auditor |
| POST | `/tenants/{tid}/audit_samples/{id}/pass` | Pass a sample | Auditor |
| POST | `/tenants/{tid}/audit_samples/{id}/fail` | Fail a sample; auto-creates a COLLECT_NEW_CERT remediation | Auditor |
| POST | `/tenants/{tid}/audit_samples/{id}/waive` | Waive a sample from DOC_REQUESTED or DOC_RECEIVED | Auditor |
| GET | `/tenants/{tid}/remediation_actions/{id}` | Get a RemediationAction | TenantAdmin, ComplianceOfficer, Auditor |
| GET | `/tenants/{tid}/audit_samples/{sid}/remediation_actions` | List remediation actions for a sample | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/audit_samples/{sid}/remediation_actions` | Create a remediation action manually | Auditor |
| POST | `/tenants/{tid}/remediation_actions/{id}/begin` | Begin work on an OPEN or ESCALATED action; assignee only | ComplianceOfficer |
| POST | `/tenants/{tid}/remediation_actions/{id}/escalate` | Escalate an IN_PROGRESS action | ComplianceOfficer |
| POST | `/tenants/{tid}/remediation_actions/{id}/resolve` | Resolve an IN_PROGRESS action; requires the parent campaign's version | ComplianceOfficer |
| POST | `/tenants/{tid}/outreach_campaigns` | Create an OutreachCampaign in DRAFT | ComplianceOfficer |
| GET | `/tenants/{tid}/outreach_campaigns/{id}` | Get an OutreachCampaign | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/outreach_campaigns/{id}/schedule` | Schedule an outreach campaign | ComplianceOfficer |
| POST | `/tenants/{tid}/outreach_campaigns/{id}/cancel` | Cancel a DRAFT or SCHEDULED outreach campaign | ComplianceOfficer |
| GET | `/tenants/{tid}/outreach_campaigns/{id}/notices` | List notices emitted by a campaign | TenantAdmin, ComplianceOfficer, Auditor |
| GET | `/tenants/{tid}/audit_campaigns/{cid}/defense_packet` | Get the defense packet for a campaign; one-to-one, returns an array of zero or one | TenantAdmin, ComplianceOfficer, Auditor |
| POST | `/tenants/{tid}/audit_defense_packets/{id}/assemble` | Assemble a packet; computes included, missing, and score | Auditor |
| POST | `/tenants/{tid}/audit_defense_packets/{id}/deliver` | Deliver an ASSEMBLED packet; requires a completeness score of 100 | Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error are defined in the narratives of §2 and §3; this catalogue is the authoritative index of identifiers to HTTP status codes.

| Error ID | HTTP Status Code |
| -------- | ---------------- |
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 Bad Request |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 Forbidden |
| `ERR_NOT_FOUND` | 404 Not Found |
| `ERR_CROSS_TENANT_REFERENCE` | 404 Not Found |
| `ERR_INVALID_STATE_TRANSITION` | 409 Conflict |
| `ERR_STALE_VERSION` | 412 Precondition Failed |
| `ERR_SOD_REVIEWER_IS_UPLOADER` | 409 Conflict |
| `ERR_SOD_CLOSER_IS_OPENER` | 409 Conflict |
| `ERR_SOD_ASSESSOR_IS_RESOLVER` | 409 Conflict |
| `ERR_FORM_NOT_ACCEPTED_IN_STATE` | 422 Unprocessable Entity |
| `ERR_MISSING_STATE_REGISTRATION` | 422 Unprocessable Entity |
| `ERR_EFFECTIVE_DATE_IN_FUTURE` | 422 Unprocessable Entity |
| `ERR_CERT_EXPIRED` | 409 Conflict |
| `ERR_SCHEDULE_IN_PAST` | 422 Unprocessable Entity |
| `ERR_ORDER_EMPTY` | 422 Unprocessable Entity |
| `ERR_ONBOARDING_INCOMPLETE` | 409 Conflict |
| `ERR_RESALE_CERT_NOT_APPROVED` | 409 Conflict |
| `ERR_DROP_SHIP_STATE_MISMATCH` | 422 Unprocessable Entity |
| `ERR_BLOCKED_EXPOSURE_AT_LIMIT` | 409 Conflict |
| `ERR_UNREMEDIATED_FAILURES` | 409 Conflict |
| `ERR_PACKET_INCOMPLETE` | 409 Conflict |
| `ERR_CERT_UNDER_AUDIT` | 409 Conflict |
| `ERR_CAMPAIGN_ALREADY_SENDING` | 409 Conflict |
| `ERR_DOC_WINDOW_EXPIRED` | 409 Conflict |
| `ERR_NO_CERT_VERSION` | 422 Unprocessable Entity |
| `ERR_DUPLICATE_REASON_CODE` | 409 Conflict |
| `ERR_DUPLICATE_JURISDICTION` | 409 Conflict |
| `ERR_ASSESSMENT_AMOUNT_INVALID` | 422 Unprocessable Entity |
