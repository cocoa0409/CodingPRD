# Foreign Trade Letter of Credit API — Product Requirements Document

## 1. Introduction

International trade finance still runs on a paper-era choreography: a corporate buyer asks its bank to underwrite payment to a foreign supplier; that bank issues a credit instrument; a network of advising, confirming and negotiating banks routes the instrument abroad; the supplier ships goods, gathers a precise stack of documents, and presents them through banking channels for payment. Each step is timed, formal, and unforgiving — UCP600's "strict compliance" doctrine means a single date out of window or a missing certificate can shift cash from the supplier back to the buyer. The system specified here digitises this choreography end to end: letter-of-credit application, term review, SWIFT messaging, document examination with multi-reviewer cross-check, discrepancy and refusal handling, sight/usance/negotiation settlement, reimbursement claims, expiration management, and an audit trail of every state change.

Two design priorities shape the rest of this document. First, every operation is performed against a strongly-stated state machine — letters of credit, amendments, presentations, examinations, settlements, and reimbursement claims each carry their own lifecycle, and the legitimate consequences of each transition (cascades to children, derived-field reconciliation, and SWIFT side effects) are pinned down rather than left to implementer discretion. Second, the workflow must be deterministic under a logical clock: refusal deadlines, usance maturities, presentation-period lapses and expiry alerts are driven by an operator-advanced clock so that the entire negotiation can be replayed in test scenarios without depending on wall time.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. If either is missing, malformed, or carries an unknown role, the request is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`. When the headers are well-formed but the role does not appear in the authorised-role list of the requested endpoint, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`.

The platform recognises eight roles. `Applicant` is the corporate buyer; `Beneficiary` is the exporter or seller; `IssuingBank`, `AdvisingBank`, `ConfirmingBank`, and `NegotiatingBank` are the four banking participants of a credit transaction; `Operator` is the platform operator who registers reference data, runs the cross-check review, ingests external-system events, and drives the test clock; `Auditor` is a read-only audit role.

For the `Applicant` role, `X-User-ID` is the `id` of the acting `Applicant` entity; ownership checks on any resource that references an applicant compare the resource's `applicant_id` to `X-User-ID`. For the `Beneficiary` role, `X-User-ID` is the `id` of the acting `Beneficiary` entity; ownership checks on any resource that references a beneficiary compare the resource's `beneficiary_id` to `X-User-ID`. For the four bank roles — `IssuingBank`, `AdvisingBank`, `ConfirmingBank`, and `NegotiatingBank` — `X-User-ID` is the `id` of the acting `Bank` entity; ownership checks on any LC, amendment, presentation, settlement or reimbursement claim compare the relevant per-role bank foreign key (`issuing_bank_id`, `advising_bank_id`, `confirming_bank_id`, or the negotiating bank reference on the corresponding settlement) to `X-User-ID`. For `Operator` and `Auditor`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server may record it (for example, as `actor_id` on `AuditLogEntry` rows) but does not compare it to any entity's `id`.

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

List endpoints accept two query parameters, `limit` and `offset`. The default `limit` is 10, the minimum is 1, and the maximum is 100; values outside that range are rejected with `ERR_INVALID_REQUEST`. The default `offset` is 0 and any non-negative integer is accepted. Results are sorted by `created_at` ascending unless an endpoint explicitly states otherwise; ties are broken by `id` ascending so that paged reads of the same dataset are stable across requests. The response `meta` block on every list endpoint includes `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and Optimistic Concurrency

Every resource the API mints carries a server-generated `id` that is a UUID with no type prefix, plus a `created_at` timestamp recorded the moment the row is inserted. Persistent resources whose state evolves over time additionally carry `updated_at` and `version`: `updated_at` advances on every successful mutation and `version` is an integer that starts at 1 and increments by 1 on each mutation. All timestamps are ISO 8601 UTC strings with three fractional digits of precision.

Two entity classes are immutable event records and therefore omit both `updated_at` and `version`: `SwiftMessage` (the audit log of MT messages emitted to the SWIFT network), `ExpiryAlert` (alerts emitted by the clock-driven sweep), `ExternalEvent` (events ingested from banking, customs, logistics, or SWIFT), `AuditLogEntry`, and the singleton `Clock` row. Each of these carries only `id` and `created_at`.

Optimistic concurrency control is offered on all mutation endpoints whose target resource has a `version` field. A request body may include an optional `version` field; when present, the server compares it to the current row's `version` and rejects any mismatch with `ERR_VERSION_CONFLICT`. When the `version` field is omitted from the body the OCC check is skipped and the operation proceeds against the current row. On every successful mutation the server bumps `version` by 1 and refreshes `updated_at` to the current server clock instant.

### 2.5. Currency, Amounts, and Rounding

All monetary amounts are carried in **minor currency units** as integers — for a USD-denominated credit, "USD 75.00" is `7500` minor units. The `currency` field on a letter of credit is an ISO 4217 three-letter code (for example `USD`, `EUR`, `JPY`, `CNY`); country codes elsewhere on `Applicant`, `Beneficiary`, and `Bank` rows are ISO 3166-1 alpha-2 codes. Bank `swift_bic` values follow ISO 9362, eight or eleven characters, and must be globally unique across all `Bank` rows.

Amount calculations follow two rules. Tolerance ceilings — converting a face amount and a percentage tolerance into a drawing cap — apply integer floor: the cap is the LC face amount multiplied by 100 plus the tolerance percentage, divided by 100, with the result floored to an integer in minor currency units. Negotiation discounts also floor at each multiplicative step. Final beneficiary proceeds are rounded once at the end using round-half-up to an integer in minor units; per-step rounding is forbidden so that two-stage formulas (fee subtraction then discount) produce a single, predictable cent figure.

### 2.6. Hierarchical Consistency and Cascade Discipline

Many operations cascade across more than one row. When a presentation settles, the system not only flips the `PaymentSettlement` to a paid state but also accumulates `LC.drawn_amount_minor_units` upward by the settlement's `principal_minor_units` and recomputes `LC.available_amount_minor_units`; both `LC.updated_at` and `LC.version` advance as part of the same transaction. When a settlement is later compensated, the same cascade runs in reverse: `drawn_amount_minor_units` is reduced by `principal_minor_units`, `available_amount_minor_units` is recomputed, and the parent `Presentation` reverts to `EXAMINED_CLEAN` so a fresh settlement can be initiated. The compensating-invariant rule is that an addition followed by its compensation must net to zero on `drawn_amount_minor_units`.

Amendment application cascades in a similar way: when the final consent flips an `LcAmendment` to `CONSENTED`, every field in `changes` is merged into the parent letter of credit row, the LC's `updated_at` and `version` advance, and `amendment_consent_status` resets to `NONE` so a subsequent amendment may begin. A reduction in `amount_minor_units` or `tolerance_pct` must trigger reconciliation of `available_amount_minor_units` because the cap shifts. Children of children — `Discrepancy` rows under `ExaminationReport`, `Document` rows under `Presentation`, `ReimbursementClaim` rows under `PaymentSettlement` — never carry their own copy of parent state; they reference the parent and read through.

### 2.7. Nested Resource Path Validation

Endpoints with multi-segment paths validate each path parameter from left to right. For a request such as a discrepancy listing under a specific examination, the server first verifies that the `examinationId` exists; if not, it returns `ERR_NOT_FOUND` without consulting any deeper segment. The same left-to-right rule applies to amendment, presentation, settlement, and reimbursement-claim sub-resources — an `amendmentId` must belong to the `lcId` named in the path; if it does not, the response is `ERR_NOT_FOUND`. Body-referenced foreign keys (`applicant_id`, `beneficiary_id`, `issuing_bank_id`, `advising_bank_id`, `confirming_bank_id`) are validated for existence after path validation and likewise yield `ERR_NOT_FOUND` on a miss.

### 2.8. Banking Calendar, Clock, and Deferred Sweeps

The system runs against a logical server `Clock` whose `now` value is the source of truth for every time-dependent rule. An operator may advance the clock via a test-driving capability that accepts a number of `seconds` to add. Every advance triggers four sweeps in sequence: the refusal-deadline sweep auto-promotes presentations whose issuing-bank refusal window has elapsed; the maturity sweep transitions usance settlements from `ACCEPTED` to `PAID`; the expiry sweep transitions letters of credit from `ACTIVE` to `EXPIRED` once `now` passes `expiry_date`; and the alert sweep emits `ExpiryAlert` rows for the `T_MINUS_15`, `T_MINUS_5`, `EXPIRED`, and `PRESENTATION_PERIOD_LAPSED` thresholds. The sweep takes a single snapshot of the clock on entry — re-running an advance with the same effective `now` does not emit duplicate alerts because emission is idempotent on the pair `(lc_id, alert_kind)`.

"Banking days" in this system count Monday through Friday strictly greater than the start date and stop counting on Saturday and Sunday; holidays are not modelled (the bank is assumed to operate on every weekday). Where a deadline is expressed in banking days, the comparison is done in integer banking days only.

### 2.9. Idempotency

Two distinct idempotency mechanisms operate in this system. **Server-derived idempotency** governs SWIFT message emission: the `idempotency_key` on a `SwiftMessage` is a deterministic function of `subject_type`, `subject_id`, and `message_type`, so a re-issue on the same triplet returns the existing message with no duplicate emission and the response is shaped as a 200 success carrying the prior row, marked internally with `ERR_IDEMPOTENT_REPLAY` semantics. **Caller-supplied idempotency** governs external-event ingestion: the caller supplies an `idempotency_key` per `source_system`, and a re-emission with the same `(source_system, idempotency_key)` pair is a no-op that returns the original `ExternalEvent` row without re-running any side effects. In both cases, idempotent replay is reported as a success-shaped response on the existing row, not as a 4xx error.

### 2.10. Audit Trail

Every state-changing operation appends a row to the audit log via an `AuditLogEntry`. The entry records the `actor_role` and `actor_id` (the value of `X-User-ID` at the time of the action, or null for system-driven transitions), an endpoint canonical `action` name (such as `'lc.issue'` or `'presentation.refuse'`), the `subject_type` and `subject_id` of the affected row, the `lc_id` (always populated so polymorphic subjects can be traced back to their letter of credit), the `before_state` and `after_state` for state transitions, and a `payload_digest` that is the SHA-256 hex of the canonical request body. Audit rows are immutable; only `id` and `created_at` are present (no `updated_at`, no `version`).

### 2.11. Validation Priority Order

When several validation checks could reject the same request, the server evaluates them in a fixed priority order so that the same input always surfaces the same error. The order is: header authentication first, then role-based authorisation, then path-resource existence, then body foreign-key existence, then state-transition legality, then cross-entity referential checks (such as amendment-vs-presentation consistency), then business-temporal checks (expiry, shipment date, usance tenor), then confirmation-requirement consistency, then reviewer segregation, then document-required and document-frozen rules, then per-presentation date-window and expiry checks, then drawing-amount availability, then amendment-pending exclusivity, then cancellation guards, then bank-role-vs-slot consistency, then SWIFT-prerequisite checks, then idempotency replay, and finally optimistic concurrency. A header-missing request, for example, surfaces `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` even when the same payload would also have failed a state check; a forbidden-role request surfaces `ERR_FORBIDDEN_FOR_ROLE` rather than a downstream business error.

## 3. Business Logic & Workflows

### 3.1. Reference Data: Banks, Applicants, and Beneficiaries

Before any letter of credit can be drafted, the platform must hold rows for the parties involved. An `Operator` registers each `Bank` with its `bank_role` (`ISSUING`, `ADVISING`, `CONFIRMING`, or `NEGOTIATING`), its `swift_bic`, its legal `name`, and its `country_code`; the row's `status` defaults to `ACTIVE` and the BIC is checked for global uniqueness. A single underlying `Bank` record may be registered under multiple bank-role rows when the same institution plays more than one role on different LCs; later, when a letter of credit is drafted, the LC's per-role foreign keys (`issuing_bank_id`, `advising_bank_id`, `confirming_bank_id`) must each resolve to a `Bank` whose `bank_role` matches the slot it fills, otherwise the request is rejected with `ERR_BANK_ROLE_MISMATCH`. The same role-vs-slot check guards the negotiation-advance flow: a negotiation settlement must be performed by a `Bank` whose `bank_role` is `NEGOTIATING`. Applicant and beneficiary registration is similarly operator-driven and creates rows carrying `name`, `country_code`, and `status`.

### 3.2. Letter of Credit Drafting and Term Review

A `corporate buyer` acting as `Applicant` initiates the workflow by drafting an LC. The draft payload names the parties — `applicant_id`, `beneficiary_id`, `issuing_bank_id`, `advising_bank_id`, and an optional `confirming_bank_id` — together with the financial and shipping terms: `lc_type` (either `SIGHT` or `USANCE`), an optional `usance_tenor_days` (mandatory when `lc_type` is `USANCE` and required to be one of 30, 60, 90, 120, or 180), `currency`, `amount_minor_units`, an optional `tolerance_pct` between 0 and 10 (defaulting to 0, meaning exact), `latest_shipment_date`, an optional `presentation_period_days` (the UCP600 default is 21), `expiry_date`, an optional `confirmation_required` flag (default false), the `required_documents` checklist, and an optional `discrepancy_fee_minor_units` per-presentation flat fee (the default fee equals 7,500 minor currency units, which is 75.00 of the LC currency).

The `required_documents` array is drawn from the enumeration `COMMERCIAL_INVOICE`, `BILL_OF_LADING`, `PACKING_LIST`, `INSURANCE_POLICY`, and `CERTIFICATE_OF_ORIGIN`; a draft must include both `COMMERCIAL_INVOICE` and `BILL_OF_LADING` at minimum, otherwise submission is rejected with `ERR_INVALID_REQUEST`. A freshly drafted LC sits in `lifecycle_status` `DRAFT` with `amendment_consent_status` `NONE` and `confirmation_status` `NOT_REQUIRED`.

When the applicant is satisfied with the draft, submission advances `lifecycle_status` from `DRAFT` to `UNDER_REVIEW`. Submission enforces a tight bundle of preconditions: the `Applicant`'s `status` must be `ACTIVE` (otherwise `ERR_APPLICANT_SUSPENDED`); the `Beneficiary`'s `status` must likewise be `ACTIVE` (otherwise `ERR_BENEFICIARY_SUSPENDED`); `required_documents` must contain both `COMMERCIAL_INVOICE` and `BILL_OF_LADING`; if `lc_type` is `USANCE` the `usance_tenor_days` must be one of the five allowed values; if `confirmation_required` is true the `confirming_bank_id` must be set (and conversely, setting one without the other) — failing this raises `ERR_CONFIRMING_BANK_REQUIRED`; `expiry_date` must be strictly later than the current server clock, otherwise `ERR_EXPIRY_IN_PAST` is returned; and `latest_shipment_date` must be on or before `expiry_date`, otherwise `ERR_SHIPMENT_AFTER_EXPIRY`. Submission writes an audit entry with action `'lc.submit'`.

The `IssuingBank` reviewer then has two paths from `UNDER_REVIEW`. Returning to the applicant rolls the LC back from `UNDER_REVIEW` to `DRAFT` for revision. Issuing the LC advances it from `UNDER_REVIEW` to `ISSUED`, assigns the immutable `lc_number` (formatted `LC-YYYY-NNNNNN` and unique across the platform), and emits an `MT700` SWIFT message. Issuance is idempotent: re-issuing an already-`ISSUED` LC returns the existing `lc_number` rather than creating a second one. If `confirmation_required` is true, `confirmation_status` flips from its default to `PENDING`; otherwise it stays at `NOT_REQUIRED`. An audit entry records `'lc.issue'`. Two simultaneous attempts to issue the same draft serialise on `LC.lifecycle_status`: exactly one writer wins, and the loser receives `ERR_INVALID_STATE_TRANSITION` because the row is no longer in the expected `from` state.

### 3.3. Advising, Confirmation, and Activation

An LC in `ISSUED` status is ready for advising. The `AdvisingBank` named on the LC advances the lifecycle from `ISSUED` to `ADVISED`, optionally naming a `downstream_advising_bank_bic` when the advice is being routed onward to a third bank — in that case an `MT710` SWIFT message is generated (idempotent on its `(subject_type, subject_id, message_type)` triplet). The advising step is gated by a SWIFT-prerequisite check: an `MT700` for the LC must already exist, otherwise the request is rejected with `ERR_SWIFT_NOT_DELIVERED`.

Whether the LC then enters `ACTIVE` depends on confirmation. If `confirmation_required` is false, the system automatically transitions the LC from `ADVISED` to `ACTIVE` because `confirmation_status` is `NOT_REQUIRED`. If `confirmation_required` is true, the LC remains in `ADVISED` until the named `ConfirmingBank` performs confirmation, which flips `confirmation_status` from `PENDING` to `CONFIRMED`; the system then automatically transitions `lifecycle_status` from `ADVISED` to `ACTIVE`. While in `ADVISED` waiting on confirmation, presentations cannot yet be submitted. The confirmation outcome `DECLINED` is also a recognised value for `confirmation_status`.

Cancellation is available out of `ISSUED`, `ADVISED`, or `ACTIVE`, but only when the LC has truly seen no use. The `IssuingBank` invokes a cancellation request supplying a `cancelled_reason` (free text). The cancellation guards are: `drawn_amount_minor_units` must be 0, otherwise `ERR_LC_HAS_DRAWINGS`; no `Presentation` may be in any of the non-terminal states `SUBMITTED`, `UNDER_EXAMINATION`, `EXAMINED_CLEAN`, `EXAMINED_DISCREPANT`, or `ACCEPTED_BY_APPLICANT`, otherwise `ERR_LC_HAS_OPEN_PRESENTATIONS`; and no `LcAmendment` may be in `PENDING`, otherwise `ERR_AMENDMENT_PENDING`. On success the LC moves to `CANCELLED`, the `cancelled_reason` is stored, and an audit entry records `'lc.cancel'`. The `cancelled_reason` field is null at all other times.

### 3.4. The Amendment Cycle: Three Consents in Series

An LC in `ISSUED`, `ADVISED`, or `ACTIVE` can be amended; any other lifecycle status produces `ERR_LC_NOT_AMENDABLE`. The `IssuingBank` initiates an amendment by posting a `changes` object — a field-level diff that may include any of `amount_minor_units`, `expiry_date`, `latest_shipment_date`, `tolerance_pct`, or `required_documents`, with at least one field required. Initiating an amendment creates an `LcAmendment` row carrying a per-LC `amendment_seq` starting at 1, sets its `applicant_consent` to `PENDING`, sets the LC's `amendment_consent_status` from `NONE` to `PENDING_APPLICANT`, and emits an `MT707` SWIFT message keyed on the new amendment's id. At most one `LcAmendment` may be `PENDING` per LC at a time — a second concurrent initiation is rejected with `ERR_AMENDMENT_PENDING`, and two simultaneous initiations on the same LC serialise on the LC's `amendment_consent_status` flip out of `NONE` so that exactly one writer wins and the loser receives `ERR_AMENDMENT_PENDING`.

The applicant decides next. The `Applicant` posts a consent payload carrying a `decision` field whose value is either `CONSENTED` or `REJECTED`; a `CONSENTED` `decision` flips `applicant_consent` to `CONSENTED` and advances `amendment_consent_status` to `PENDING_BENEFICIARY`, while a `REJECTED` `decision` sets `applicant_consent` to `REJECTED`, the row's `status` to `REJECTED`, `rejected_by_role` to `APPLICANT`, and resets the LC's `amendment_consent_status` to `NONE` so a fresh amendment may begin. The `Beneficiary` then posts a similar `decision`: `CONSENTED` flips `beneficiary_consent` and the LC's `amendment_consent_status` advances to `PENDING_CONFIRMING_BANK` if the LC has a `confirming_bank_id`, or directly to the system-driven `CONSENTED` final state if there is no confirming bank; `REJECTED` sets `rejected_by_role` to `BENEFICIARY` and resets the cycle. The `ConfirmingBank` posts the final `decision` when applicable, flipping `confirming_bank_consent` and either driving the amendment to `CONSENTED` or rejecting with `rejected_by_role` `CONFIRMING_BANK`.

When all required consents are collected, the system automatically moves the `LcAmendment` from `PENDING` to `CONSENTED`, sets `applied_at` to the current server clock, and resets the LC's `amendment_consent_status` to `NONE`. As part of the same transaction it merges every field of `changes` into the parent LC row. A reduction in `amount_minor_units` or `tolerance_pct` triggers reconciliation of `available_amount_minor_units`. The merge is also subject to a cross-entity referential check evaluated at the moment of the consenting decision: any new `latest_shipment_date` must be on or after every existing `Presentation.shipment_date` under the LC, and similarly for any other field whose change would invalidate an already-recorded presentation. If the merge would violate this rule the consenting decision is rejected with `ERR_AMENDMENT_VIOLATES_PRESENTATIONS`. Beneficiary or confirming-bank consent attempts before the applicant has consented are rejected with `ERR_AMENDMENT_CONSENT_OUT_OF_ORDER`, and any consent attempt on a row whose `status` is no longer `PENDING` is rejected with `ERR_AMENDMENT_ALREADY_DECIDED`.

When any consent flips to `REJECTED`, the system automatically moves the `LcAmendment` to terminal `REJECTED` and records `rejected_by_role`. Withdrawal is also possible: the `IssuingBank` may withdraw a `PENDING` amendment, but only before the applicant has consented — once `applicant_consent` is `CONSENTED`, withdrawal is no longer permitted. Withdrawal moves the row to `WITHDRAWN` and resets `amendment_consent_status` to `NONE`. Throughout the cycle, the LC's `amendment_consent_status` and its `lifecycle_status` evolve independently: an LC in `ACTIVE` may be in any one of the five `amendment_consent_status` values, and either dimension reaches its terminal state independently of the other.

### 3.5. Presentation, Document Attachment, and Examination Start

The exporter, acting as `Beneficiary`, initiates a draw by submitting a presentation. The presentation payload carries a `shipment_date` and a `drawing_amount_minor_units`. The system mints a `presentation_seq` per LC starting at 1, sets `presented_at` to the server clock, and starts the row in `status` `SUBMITTED`. Two checks guard the submission. The `shipment_date` must be on or before the LC's `latest_shipment_date` and on or before the current server clock — if either condition fails the request is rejected with `ERR_SHIPMENT_OUT_OF_WINDOW`. The `presented_at` must be on or before the LC's `expiry_date` — a presentation against an already-expired LC is rejected with `ERR_PRESENTATION_AFTER_EXPIRY`. The `drawing_amount_minor_units` must be strictly positive and must not exceed `available_amount_minor_units`; an over-draw raises `ERR_LC_INSUFFICIENT_AVAILABLE`.

`available_amount_minor_units` is a derived quantity computed as follows. The drawing cap is the LC's `amount_minor_units` multiplied by 100 plus `tolerance_pct`, divided by 100, with the result floored to an integer in minor units. The drawn portion is the sum, across all `PaymentSettlement` rows whose `lc_id` matches and whose `status` is in the set `ACCEPTED` or `PAID` (excluding both `PENDING` rows that have not yet drawn and `COMPENSATED` rows that have been reversed), of each settlement's `principal_minor_units`. The available amount is then the cap minus the drawn portion, with the result clamped to be no less than zero. Two beneficiaries that submit presentations on the same LC simultaneously, where each fits under the available amount on its own but together would overdraw, serialise on `LC.id`: the first writer's deduction lands and the second presentation's check fails with `ERR_LC_INSUFFICIENT_AVAILABLE`.

Once the presentation row exists, the beneficiary attaches each `Document` referenced by `required_documents`. Each `Document` carries a `document_type` (one of `COMMERCIAL_INVOICE`, `BILL_OF_LADING`, `PACKING_LIST`, `INSURANCE_POLICY`, `CERTIFICATE_OF_ORIGIN`), an `issuer` (free text), a `document_date`, an optional `stated_amount_minor_units` (zero when not applicable to the type), an optional `stated_currency` (mirroring the LC currency when the document does not state its own), and a structured `payload` that varies by document type — for example a `BILL_OF_LADING` payload includes `shipped_on_board_date`, and a `CERTIFICATE_OF_ORIGIN` payload includes `country_of_origin`. The document is rejected with `ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE` when its `document_type` does not appear in the LC's `required_documents` list or when it duplicates an existing document of the same type for the same presentation; the only `document_type` that may legitimately duplicate per presentation is `COMMERCIAL_INVOICE`.

The `IssuingBank` starts examination by naming a `primary_reviewer_id` and a `secondary_reviewer_id`, both of which must be `Operator` users and the secondary must differ from the primary, otherwise the request is rejected with `ERR_REVIEWER_SAME_PERSON`. Starting examination cascades: the presentation moves from `SUBMITTED` to `UNDER_EXAMINATION`, an `ExaminationReport` is created in `IN_PROGRESS` with `deadline_at` set to the presentation's `presented_at` plus 5 banking days (the UCP600 reasonable-time-not-to-exceed-five-banking-days standard), and from this moment the document set is FROZEN — any subsequent attempt to attach or mutate a document on this presentation is rejected with `ERR_DOCUMENTS_FROZEN` until either examination is `FINALIZED` or the report is `RESET` after a `CONFLICT`.

### 3.6. The Multi-Reviewer Cross-Check and Compliance Algorithm

Examination is a two-pass review. The primary reviewer (whose `X-User-ID` must equal the report's `primary_reviewer_id`) submits a `primary_outcome` of `CLEAN` or `DISCREPANT` together with a list of `discrepancies` when the outcome is `DISCREPANT`. Each `Discrepancy` row carries a `discrepancy_code` from the enumeration `MISSING_DOCUMENT`, `LATE_PRESENTATION`, `LATE_SHIPMENT`, `AMOUNT_MISMATCH`, `DESCRIPTION_MISMATCH`, `INCONSISTENT_DOCS`, `EXPIRED_LC`, `CURRENCY_MISMATCH`, a reviewer-authored `description`, and an optional `cited_document_id` pointing at the offending `Document` (left null when the discrepancy is about an absent document). The report's `status` advances from `IN_PROGRESS` to `PRIMARY_DONE`. Two reviewers attempting to submit the same primary review simultaneously serialise on `ExaminationReport.primary_outcome`: the first writer wins and the second receives `ERR_REVIEW_ALREADY_RECORDED`.

Each `Discrepancy` row carries `examination_report_id` referencing the parent report. The secondary reviewer (whose `X-User-ID` must equal the report's `secondary_reviewer_id`) submits a `secondary_outcome` and an independent discrepancy list. Both reviewers read the same frozen document set — documents are immutable while the presentation sits in `UNDER_EXAMINATION`, which resolves the otherwise-ambiguous question of whether cross-check sees post-primary edits (it does not). When `primary_outcome` equals `secondary_outcome` the report's `status` advances from `PRIMARY_DONE` to `CROSS_CHECK_DONE`; when they diverge the status advances instead to `CONFLICT`. A cross-check submitted before any primary outcome has been recorded is rejected with `ERR_REVIEW_OUT_OF_ORDER`. From `CONFLICT` the `IssuingBank` may reset the report back to `IN_PROGRESS`, which clears `primary_outcome` and `secondary_outcome` and deletes every `Discrepancy` row attached to the report; documents nonetheless remain frozen.

Compliance itself is a deterministic seven-input check. Let I1 be the requirement that the set of `document_type` values present in the presentation contains the LC's `required_documents`; let I2 be the requirement that the sum of invoice amounts is on or below the LC's `amount_minor_units` multiplied by 100 plus `tolerance_pct`, divided by 100; let I3 be the requirement that every document's `stated_currency` equals the LC's `currency`; let I4 be the requirement that the latest `shipped_on_board_date` across bills of lading is on or before the LC's `latest_shipment_date`; let I5 be the requirement that the presentation's `presented_at` is on or before the latest bill-of-lading `shipped_on_board_date` plus the LC's `presentation_period_days`; let I6 be the requirement that the presentation's `presented_at` is on or before the LC's `expiry_date`; and let I7 be the requirement that, when both a `COMMERCIAL_INVOICE` and a `CERTIFICATE_OF_ORIGIN` are present, the country-of-origin fields on the two documents agree. The compliance outcome is `CLEAN` if and only if all seven checks hold; otherwise it is `DISCREPANT` and the discrepancy list is emitted in the strict order I1 through I7. The mapping from check to discrepancy is fixed: I1 produces `MISSING_DOCUMENT`, I2 produces `AMOUNT_MISMATCH`, I3 produces `CURRENCY_MISMATCH`, I4 produces `LATE_SHIPMENT`, I5 produces `LATE_PRESENTATION`, I6 produces `EXPIRED_LC`, and I7 produces `INCONSISTENT_DOCS`. The default `presentation_period_days` is 21, but any value carried on the LC overrides the default. Both reviewers run the same algorithm against the same frozen documents.

Finalisation is a separate `IssuingBank` action. It requires `status` to be `CROSS_CHECK_DONE` and the report's `primary_outcome` and `secondary_outcome` to agree (otherwise the cross-check would have produced a `CONFLICT`). It also requires that the current server clock be on or before `deadline_at`; an attempt to finalise after that boundary is rejected with `ERR_EXAMINATION_DEADLINE_PASSED`. On success, the report's `status` advances to `FINALIZED`, `examined_at` is set to the current clock instant, `final_outcome` is computed (`CLEAN` if and only if both individual outcomes are `CLEAN`, else `DISCREPANT`), the `report_payload` narrative is generated covering the required-document checklist outcome and the term-by-term findings, and the parent `Presentation` cascades from `UNDER_EXAMINATION` to either `EXAMINED_CLEAN` or `EXAMINED_DISCREPANT`.

### 3.7. Discrepancy Handling, Refusal, and the UCP600 Five-Banking-Day Window

When a presentation lands in `EXAMINED_DISCREPANT`, three branches open. The applicant may decide on the discrepancies as a whole by posting a `decision` of either `ACCEPTED` or `REJECTED`: an `ACCEPTED` `decision` flips every `Discrepancy.applicant_action` to `ACCEPTED`, sets each `action_at` to the current clock, and advances the presentation to `ACCEPTED_BY_APPLICANT`. A `REJECTED` `decision` flips every `applicant_action` to `REJECTED` and advances the presentation to `REFUSED`, setting `refusal_notified_at` to the current clock and `refusal_deadline` to the current clock plus 5 banking days. The `IssuingBank` may also independently refuse the presentation with a `refusal_reason`, which moves the row directly from `EXAMINED_DISCREPANT` to `REFUSED` and writes the same `refusal_notified_at` and `refusal_deadline` fields. An applicant action and a simultaneous issuing-bank refusal serialise on `Presentation.status`: exactly one writer wins, and the loser sees `ERR_INVALID_STATE_TRANSITION`.

UCP600 article 16(d)/(f) imposes a hard deadline on the issuing bank's right to refuse: more than five banking days must not elapse between the presentation's `presented_at` and the issuing-bank refusal. The boundary comparison is strict — exactly five banking days is still within the window, but more than five is past it. The clock-driven refusal-deadline sweep enforces this on every clock advance: when the elapsed banking-day count between the presentation's `presented_at` and the current clock is strictly greater than 5, the presentation's `status` is still `EXAMINED_DISCREPANT`, and `refusal_notified_at` is null, the system auto-promotes the presentation to `EXAMINED_CLEAN` because the issuing bank has lost its right to refuse and the documents are deemed compliant. An issuing-bank refuse call after the same boundary is rejected with `ERR_REFUSAL_DEADLINE_PASSED`. Banking days for this calculation count Monday through Friday strictly greater than the start date.

From `REFUSED`, two further moves are permitted. The `IssuingBank` returns documents — moving the row from `REFUSED` to `RETURNED` — but only within seven banking days of `refusal_notified_at`; a return attempt outside that window is rejected with `ERR_RETURN_WINDOW_PASSED`. Alternatively, the `Applicant` may override refusal — a compensating action that moves `REFUSED` back to `ACCEPTED_BY_APPLICANT`, sets each `Discrepancy.applicant_action` to `ACCEPTED`, and nulls out both `refusal_notified_at` and `refusal_deadline`. Override is only valid while the current clock is on or before `refusal_deadline`.

### 3.8. Settlement Variants: Sight, Usance Acceptance, and Negotiation

A presentation in `EXAMINED_CLEAN` or `ACCEPTED_BY_APPLICANT` is ready for settlement. Settlement creation is the bridge between the document-examination world and the cash world: a settlement row is initialised in `PENDING`, its `principal_minor_units` is set equal to the presentation's `drawing_amount_minor_units`, and its `settlement_type` is determined by the LC's `lc_type` — `SIGHT_PAYMENT` for sight LCs, `USANCE_ACCEPTANCE` for usance LCs — except when a `settlement_type_override` of `NEGOTIATION` is supplied at creation, which is the only legal override and is restricted to flows where a `NegotiatingBank` is initiating the advance. A creation request whose effective `settlement_type` does not match the parent LC's `lc_type` (other than the legal NEGOTIATION override) is rejected with `ERR_SETTLEMENT_TYPE_MISMATCH`.

The sight-payment branch is the simplest. The `IssuingBank` executes sight payment, which advances the settlement from `PENDING` to `PAID`, sets `paid_at` to the current clock, and computes `beneficiary_proceeds_minor_units` from the proceeds formula described shortly. As cascade, `LC.drawn_amount_minor_units` is incremented by the settlement's `principal_minor_units` and `available_amount_minor_units` is recomputed. An execute-sight call on a non-`SIGHT_PAYMENT` settlement is rejected with `ERR_SETTLEMENT_TYPE_MISMATCH`.

The usance branch is two-step. The `IssuingBank` records acceptance, which moves the settlement from `PENDING` to `ACCEPTED`, sets `accepted_at` to the current clock, computes `maturity_date` as `accepted_at` plus the LC's `usance_tenor_days`, and increments `LC.drawn_amount_minor_units`. From `ACCEPTED` the system then waits for the maturity sweep: on every clock advance, any usance settlement whose current clock has reached or passed `maturity_date` automatically advances from `ACCEPTED` to `PAID`, with `paid_at` set to the sweep instant and `beneficiary_proceeds_minor_units` computed. Manual override of the maturity wait is forbidden — an explicit payment call before the maturity_date is rejected with `ERR_MATURITY_NOT_REACHED`. A record-acceptance call on a non-`USANCE_ACCEPTANCE` settlement is rejected with `ERR_SETTLEMENT_TYPE_MISMATCH`.

The negotiation branch involves a `NegotiatingBank` advancing funds before the issuing bank reimburses. The `NegotiatingBank` posts a negotiation-advance, which moves the settlement from `PENDING` to `PAID`, sets `paid_at` to the current clock, computes both `negotiation_advance_minor_units` and `negotiation_discount_minor_units`, and as cascade auto-creates a `ReimbursementClaim` in `SUBMITTED` whose `claimed_amount_minor_units` equals the settlement's `principal_minor_units`. The presentation must be in `EXAMINED_CLEAN` for negotiation; an advance against a non-`NEGOTIATION` settlement is rejected with `ERR_SETTLEMENT_TYPE_MISMATCH`.

The proceeds calculation is consistent across variants and is run once at the moment funds disburse. Begin with a base equal to the settlement's `principal_minor_units` minus a discrepancy fee. The fee is the LC's `discrepancy_fee_minor_units` flat per-presentation amount when the presentation's history includes a passage through `EXAMINED_DISCREPANT` followed by `ACCEPTED_BY_APPLICANT`; otherwise the fee is zero. Crucially the check is "was-ever-`EXAMINED_DISCREPANT`" rather than current status, because a presentation auto-promoted from `EXAMINED_DISCREPANT` to `EXAMINED_CLEAN` by the refusal-deadline sweep must NOT be charged the fee — the issuing bank lost its right to refuse and, under UCP600 article 16(d)/(f), the documents are deemed compliant. The fee is subtracted from the principal first, then the negotiation discount (if any) is applied; rounding is performed once at the end on the final `beneficiary_proceeds_minor_units` using round-half-up, never per step.

For sight and usance the discount is zero, so `beneficiary_proceeds_minor_units` equals base. For negotiation the discount captures funds-time-value: the rate is 350 basis points annualised (3.50%) and the assumed time to reimbursement is 7 days; the rate fraction is therefore 350 divided by 10,000 multiplied by 7 divided by 360, applied to base, with the multiplicative result floored to an integer in minor units to produce `negotiation_discount_minor_units`. The advance is then `negotiation_advance_minor_units` equal to base minus the discount, and `beneficiary_proceeds_minor_units` equals the advance. Note that the issuing bank later reimburses on `claimed_amount_minor_units` equal to `principal_minor_units` (not on base) — the discrepancy fee stays with the issuing bank and the negotiation discount stays with the negotiating bank. The fee variant `AT_SETTLE` applies on the regular settle path; the fee variant `AT_AUTO_PROMOTION` (the refusal-deadline auto-promotion path) is the no-fee case.

Compensation is the reversal channel. The `IssuingBank` may compensate a `PAID` settlement by supplying a `reason`. The trigger conditions are an `ERR_REIMBURSEMENT_ALREADY_HONORED`-incompatible `ReimbursementClaim.status` of `DISPUTED`, or the absence (or reversal) of an external `BANK_PAYMENT_CONFIRMED` event. Compensation moves the settlement to `COMPENSATED`, decrements `LC.drawn_amount_minor_units` by `principal_minor_units`, recomputes `available_amount_minor_units`, and reverts the parent `Presentation` to `EXAMINED_CLEAN` so that a fresh settlement may be initiated.

### 3.9. Reimbursement of the Negotiating Bank

The `NegotiatingBank` that has advanced funds expects reimbursement from the `IssuingBank`. The auto-created `ReimbursementClaim` carries `payment_settlement_id` pointing back to its originating settlement and starts in `SUBMITTED` with `honored_amount_minor_units` defaulting to zero. The `IssuingBank` honours the claim — moving it from `SUBMITTED` (or from `DISPUTED`) to `HONORED`, setting `honored_amount_minor_units` equal to `claimed_amount_minor_units`, and stamping `honored_at` to the current clock. Honour requires that `claimed_amount_minor_units` lie within the LC's available headroom plus its already-drawn portion. A second honour or dispute on an already-`HONORED` claim is rejected with `ERR_REIMBURSEMENT_ALREADY_HONORED`. Alternatively the `IssuingBank` may dispute the claim, with a `reason` — which moves it from `SUBMITTED` to `DISPUTED` and cascades a settlement compensation to `COMPENSATED`. From `DISPUTED` the `NegotiatingBank` may extinguish the claim, moving it to terminal `EXTINGUISHED`; or the issuing bank may relent and honour after all.

### 3.10. SWIFT Messaging, External Events, and Test-Driven Operations

SWIFT messages are immutable event log rows emitted by lifecycle transitions: `MT700` for LC issuance, `MT707` for LC amendment, and `MT710` for advising-bank routing to a downstream bank. Each row carries a `message_type`, a `subject_type` (`LC` for an `MT700` or `MT710`, `AMENDMENT` for an `MT707`), a `subject_id` polymorphically pointing at the relevant row, an `lc_id` always denormalised to the LC the message ultimately concerns, a `sender_bic` and a `receiver_bic`, a generated structured `payload` (which is never null), and a server-derived `idempotency_key` deterministically equal to the function of `subject_type`, `subject_id`, and `message_type`. Two emissions for the same triplet return the same existing message rather than minting a duplicate. SWIFT messages are listable per LC, and the list endpoint accepts an optional `message_type` query parameter alongside the standard pagination parameters.

`ExpiryAlert` rows are emitted by the alert sweep on every clock advance. For each LC whose `lifecycle_status` is in `ACTIVE`, `ADVISED`, or `ISSUED`, the sweep computes `days_to_expiry` as the LC's `expiry_date` minus the current clock divided by 86,400 seconds with the result rounded up to a whole day. When `days_to_expiry` equals 15 and no `T_MINUS_15` alert exists for the LC, the sweep emits one with `alert_kind` `T_MINUS_15`. When `days_to_expiry` equals 5 and no `T_MINUS_5` alert exists, the sweep emits one with `alert_kind` `T_MINUS_5`. When `days_to_expiry` is on or below zero and no `EXPIRED` alert exists, the sweep emits one with `alert_kind` `EXPIRED` and transitions the LC from `ACTIVE` to `EXPIRED`; this alert is idempotent on `lc_id`. Separately, for each LC's open presentations sitting in `EXAMINED_DISCREPANT` or `REFUSED`, when `Presentation.shipment_date` plus the LC's `presentation_period_days` is earlier than the current clock and no `PRESENTATION_PERIOD_LAPSED` alert yet exists, the sweep emits one with `alert_kind` `PRESENTATION_PERIOD_LAPSED`. Each alert row carries a `triggered_at` timestamp and a `details` object snapshotting `expiry_date`, `latest_shipment_date`, and `lifecycle_status` at trigger. Alerts are emitted in deterministic order: by `lc_id` ascending, then by `alert_kind` alphabetically.

When an LC enters `EXPIRED`, any open presentations in `SUBMITTED` or `UNDER_EXAMINATION` cascade to `RETURNED` as a forced transition. The LC eventually moves from `EXPIRED` to `CLOSED` automatically once every child `Presentation` has reached one of the terminal statuses `RETURNED` or `SETTLED` and the current clock has reached `expiry_date` plus 30 days. An LC can also transition automatically from `ACTIVE` to `CLOSED` once `available_amount_minor_units` is zero and no presentation is in a non-terminal state. Both terminal closures write an audit entry.

External events synchronise the platform with banking, customs, logistics, and SWIFT systems. An `Operator` posts an event identifying its `source_system` (one of `BANKING`, `CUSTOMS`, `LOGISTICS`, `SWIFT`), an `event_type` from the enumeration (`BANK_PAYMENT_CONFIRMED`, `CUSTOMS_DECLARATION_FILED`, `SHIPMENT_DEPARTED`, `SHIPMENT_DELIVERED`, `SWIFT_ACK`, `SWIFT_NAK`), the `lc_id` the event concerns, an optional `presentation_id` when the event is presentation-scoped, a caller-supplied `idempotency_key`, and a source-system-specific `payload`. The server timestamps the event with `processed_at` (immutable) and records the names of every transition or calculation triggered in `applied_side_effects`. Re-emission with the same `(source_system, idempotency_key)` pair returns the prior event row, success-shaped, without re-running side effects. Two simultaneous ingestions with the same key serialise on the unique constraint.

The test-driving capability advances the singleton `Clock` row's `now` field by a supplied number of `seconds`. Clock advance is the trigger for every deferred sweep: refusal-deadline auto-promotion of `EXAMINED_DISCREPANT` to `EXAMINED_CLEAN`, maturity transition of `ACCEPTED` settlements to `PAID`, lifecycle transition of `ACTIVE` LCs to `EXPIRED`, and emission of `ExpiryAlert` rows. A simple read-only capability returns the current `Clock` value.

## 4. Endpoint Definitions

The endpoint table below is a navigation aid only — request bodies, response payloads, and side effects are described in §3 above. Status code conventions: endpoints that mint a new resource return 201 Created; endpoints that modify, transition, or read an existing resource return 200 OK. The base path for letters of credit is `/letters-of-credit`. Resources reachable directly by id (presentations, examinations, settlements, reimbursement claims, banks, applicants, beneficiaries, swift messages, external events, the clock) are mounted at their own top-level paths.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | `/banks` | Register a Bank (issuing/advising/confirming/negotiating) | Operator |
| GET | `/banks/{bankId}` | Get a Bank | Operator, Auditor, IssuingBank, AdvisingBank, ConfirmingBank, NegotiatingBank, Applicant, Beneficiary |
| POST | `/applicants` | Register an Applicant | Operator |
| POST | `/beneficiaries` | Register a Beneficiary | Operator |
| POST | `/letters-of-credit` | Create a draft LC application | Applicant |
| GET | `/letters-of-credit/{lcId}` | Get LC | Applicant, Beneficiary, IssuingBank, AdvisingBank, ConfirmingBank, NegotiatingBank, Operator, Auditor |
| GET | `/letters-of-credit` | List LCs | Operator, Auditor, IssuingBank, AdvisingBank, ConfirmingBank, Applicant, Beneficiary |
| POST | `/letters-of-credit/{lcId}/submit` | Submit LC for issuing-bank review | Applicant |
| POST | `/letters-of-credit/{lcId}/return-to-applicant` | Return LC for revision | IssuingBank |
| POST | `/letters-of-credit/{lcId}/issue` | Issue the LC; generate MT700 | IssuingBank |
| POST | `/letters-of-credit/{lcId}/advise` | Advise the LC; may generate MT710 | AdvisingBank |
| POST | `/letters-of-credit/{lcId}/confirm` | Confirm the LC | ConfirmingBank |
| POST | `/letters-of-credit/{lcId}/cancel` | Cancel an unused LC | IssuingBank |
| POST | `/letters-of-credit/{lcId}/amendments` | Initiate LC amendment | IssuingBank |
| GET | `/letters-of-credit/{lcId}/amendments/{amendmentId}` | Get amendment | Applicant, Beneficiary, IssuingBank, AdvisingBank, ConfirmingBank, Operator, Auditor |
| GET | `/letters-of-credit/{lcId}/amendments` | List amendments | Applicant, Beneficiary, IssuingBank, AdvisingBank, ConfirmingBank, Operator, Auditor |
| POST | `/letters-of-credit/{lcId}/amendments/{amendmentId}/applicant-consent` | Applicant consents to or rejects amendment | Applicant |
| POST | `/letters-of-credit/{lcId}/amendments/{amendmentId}/beneficiary-consent` | Beneficiary consents to or rejects amendment | Beneficiary |
| POST | `/letters-of-credit/{lcId}/amendments/{amendmentId}/confirming-bank-consent` | Confirming bank consents to or rejects amendment | ConfirmingBank |
| POST | `/letters-of-credit/{lcId}/amendments/{amendmentId}/withdraw` | Withdraw a pending amendment | IssuingBank |
| POST | `/letters-of-credit/{lcId}/presentations` | Submit document presentation | Beneficiary |
| GET | `/presentations/{presentationId}` | Get presentation | Applicant, Beneficiary, IssuingBank, ConfirmingBank, NegotiatingBank, Operator, Auditor |
| GET | `/letters-of-credit/{lcId}/presentations` | List presentations under an LC | Applicant, Beneficiary, IssuingBank, ConfirmingBank, NegotiatingBank, Operator, Auditor |
| POST | `/presentations/{presentationId}/documents` | Attach a document to a presentation | Beneficiary |
| POST | `/presentations/{presentationId}/start-examination` | Start examination, naming both reviewers | IssuingBank |
| POST | `/examinations/{examinationId}/primary-review` | Submit primary review | Operator |
| POST | `/examinations/{examinationId}/cross-check` | Submit secondary cross-check | Operator |
| POST | `/examinations/{examinationId}/reset` | Reset examination after CONFLICT | IssuingBank |
| POST | `/examinations/{examinationId}/finalize` | Finalize examination | IssuingBank |
| GET | `/examinations/{examinationId}` | Get examination report | Applicant, IssuingBank, ConfirmingBank, NegotiatingBank, Operator, Auditor |
| GET | `/examinations/{examinationId}/discrepancies` | List discrepancies | Applicant, IssuingBank, Operator, Auditor |
| POST | `/presentations/{presentationId}/applicant-decision` | Applicant decides on discrepancies | Applicant |
| POST | `/presentations/{presentationId}/refuse` | Issuing bank refuses presentation | IssuingBank |
| POST | `/presentations/{presentationId}/applicant-override` | Applicant overrides refusal | Applicant |
| POST | `/presentations/{presentationId}/return-documents` | Return refused documents | IssuingBank |
| POST | `/presentations/{presentationId}/settlements` | Create settlement skeleton | IssuingBank, NegotiatingBank |
| POST | `/settlements/{settlementId}/execute-sight` | Execute sight payment | IssuingBank |
| POST | `/settlements/{settlementId}/record-acceptance` | Record usance acceptance | IssuingBank |
| POST | `/settlements/{settlementId}/negotiation-advance` | Advance funds against negotiated documents | NegotiatingBank |
| POST | `/settlements/{settlementId}/compensate` | Compensate a paid/accepted settlement | IssuingBank |
| GET | `/settlements/{settlementId}` | Get settlement | Applicant, Beneficiary, IssuingBank, NegotiatingBank, ConfirmingBank, Operator, Auditor |
| GET | `/reimbursement-claims/{claimId}` | Get reimbursement claim | IssuingBank, NegotiatingBank, Operator, Auditor |
| POST | `/reimbursement-claims/{claimId}/honor` | Honor the reimbursement claim | IssuingBank |
| POST | `/reimbursement-claims/{claimId}/dispute` | Dispute the claim (cascades to settlement compensation) | IssuingBank |
| POST | `/reimbursement-claims/{claimId}/extinguish` | Extinguish disputed claim | NegotiatingBank |
| GET | `/swift-messages/{messageId}` | Get a SWIFT message | IssuingBank, AdvisingBank, ConfirmingBank, Operator, Auditor |
| GET | `/letters-of-credit/{lcId}/swift-messages` | List SWIFT messages bound to an LC | IssuingBank, AdvisingBank, ConfirmingBank, Operator, Auditor |
| GET | `/letters-of-credit/{lcId}/expiry-alerts` | List expiry alerts for an LC | Applicant, Beneficiary, IssuingBank, Operator, Auditor |
| POST | `/external-events` | Ingest an external event | Operator |
| GET | `/external-events/{eventId}` | Get an external event | Operator, Auditor |
| GET | `/letters-of-credit/{lcId}/audit-log` | Read the audit log for an LC | Operator, Auditor, IssuingBank |
| POST | `/_clock/advance` | Advance the server clock (test-driving) | Operator |
| GET | `/_clock` | Get current server clock | Operator, Auditor |

## 5. Error Code Catalogue

Trigger conditions for each error are scattered through §2 and §3 above; this table is a reference of identifier and HTTP status only.

| Error ID | HTTP Status Code |
|---|---|
| `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` | 400 |
| `ERR_FORBIDDEN_FOR_ROLE` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_INVALID_REQUEST` | 400 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_IDEMPOTENT_REPLAY` | 200 |
| `ERR_INVALID_STATE_TRANSITION` | 409 |
| `ERR_APPLICANT_SUSPENDED` | 409 |
| `ERR_BENEFICIARY_SUSPENDED` | 409 |
| `ERR_BANK_ROLE_MISMATCH` | 422 |
| `ERR_CONFIRMING_BANK_REQUIRED` | 409 |
| `ERR_EXPIRY_IN_PAST` | 422 |
| `ERR_SHIPMENT_AFTER_EXPIRY` | 422 |
| `ERR_SWIFT_NOT_DELIVERED` | 409 |
| `ERR_LC_HAS_DRAWINGS` | 409 |
| `ERR_LC_HAS_OPEN_PRESENTATIONS` | 409 |
| `ERR_LC_INSUFFICIENT_AVAILABLE` | 409 |
| `ERR_LC_NOT_AMENDABLE` | 409 |
| `ERR_PRESENTATION_AFTER_EXPIRY` | 409 |
| `ERR_SHIPMENT_OUT_OF_WINDOW` | 422 |
| `ERR_AMENDMENT_PENDING` | 409 |
| `ERR_AMENDMENT_VIOLATES_PRESENTATIONS` | 409 |
| `ERR_AMENDMENT_CONSENT_OUT_OF_ORDER` | 409 |
| `ERR_AMENDMENT_ALREADY_DECIDED` | 409 |
| `ERR_REVIEWER_SAME_PERSON` | 422 |
| `ERR_REVIEW_ALREADY_RECORDED` | 409 |
| `ERR_REVIEW_OUT_OF_ORDER` | 409 |
| `ERR_DOCUMENTS_FROZEN` | 409 |
| `ERR_DOCUMENT_NOT_REQUIRED_OR_DUPLICATE` | 422 |
| `ERR_EXAMINATION_DEADLINE_PASSED` | 409 |
| `ERR_REFUSAL_DEADLINE_PASSED` | 409 |
| `ERR_RETURN_WINDOW_PASSED` | 409 |
| `ERR_SETTLEMENT_TYPE_MISMATCH` | 422 |
| `ERR_MATURITY_NOT_REACHED` | 409 |
| `ERR_REIMBURSEMENT_ALREADY_HONORED` | 409 |
