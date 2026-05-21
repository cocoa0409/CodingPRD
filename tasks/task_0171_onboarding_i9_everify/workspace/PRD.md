# Onboarding I-9 & E-Verify API — Product Requirements Document

## 1. Introduction

Every U.S. employer is obligated to verify, within a tight statutory window, that each new hire is who they claim to be and is legally authorized to work. The paperwork sounds simple — examine identity documents, sign a form, run an electronic check — but in practice the process is a tangle of overlapping deadlines, segregation-of-duties rules, branching outcomes from the federal E-Verify service, and follow-on reverification obligations that can stretch years into the future. Manual handling of this workflow regularly produces compliance gaps that surface only during a federal audit, by which time corrective action is no longer available.

The Onboarding I-9 & E-Verify API standardizes this lifecycle behind a single audited surface. It anchors each onboarding case to a logical clock so that deadlines are deterministic, enforces a strict separation between the role that attests and the role that examines, models E-Verify's branching outcomes — Employment Authorized, Tentative Nonconfirmation, Final Nonconfirmation — as a first-class state machine, and automatically opens reverification events when a work authorization is dated. STEM extensions for F-1 OPT students, document receipts, rehires within three years, late submissions, and idempotent retries are all modeled explicitly rather than left to the implementer's judgement. The product target is a compliance officer who must be able to reconstruct, from the audit trail alone, why every employee reached the status they did.

## 2. Global Specifications & System-Wide Principles

This section defines the system-wide rules, principles, and contracts that apply across the entire API.

### 2.1. User and Role-Based Access Control

All requests to the API must carry two mandatory headers: `X-User-ID` identifying the acting principal, and `X-User-Role` declaring their operational capacity. A request that omits or malforms either header is rejected with `ERR_AUTH_MISSING`. A request whose role is not authorized for the endpoint it targets is rejected with `ERR_FORBIDDEN`.

The system recognizes exactly four roles, spelled as shown: `Employee`, `HRStaff`, `EmployerRep`, and `System`.

When `X-User-Role` is `Employee`, `X-User-ID` is the `id` of the acting `Employee`; any ownership check on a resource that references an employee compares the resource's `employee_id` to `X-User-ID`. When `X-User-Role` is `HRStaff`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity — the server may record it in audit entries (for example, as `actor_user_id` on `AuditEvent`) but does not compare it to any entity's `id`. When `X-User-Role` is `EmployerRep`, `X-User-ID` is likewise an opaque operator identifier, recorded into `section2_completed_by_user_id` on the `I9Form` they sign and into `actor_user_id` on the corresponding `AuditEvent`, but never matched against an entity row. When `X-User-Role` is `System`, `X-User-ID` is an arbitrary operator identifier representing test or platform automation; the server stores it on `AuditEvent.actor_user_id` when present but does not require it to refer to any persisted entity.

Segregation of duties is a fundamental property of this API. The Section 1 attestation and the Section 2 examination must be performed by different principals: an `EmployerRep` who signs Section 2 with the same `X-User-ID` as the `Employee` who attested Section 1 is rejected with `ERR_SEGREGATION_OF_DUTIES`. Likewise, `HRStaff` cannot perform Employee attestations or EmployerRep document examinations, and `EmployerRep` cannot perform HR actions such as creating Employees or voiding forms.

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

For endpoints that return lists of resources, pagination is controlled via query parameters. The `limit` parameter specifies the maximum number of items to return; it defaults to 10 when omitted, with a minimum accepted value of 1 and a maximum of 100. The `offset` parameter specifies the number of items to skip and defaults to 0; values below 0 are rejected. A `limit` outside the inclusive range from 1 to 100, or a negative `offset`, yields `ERR_PAGINATION`.

Unless otherwise noted, all list endpoints sort their results by `created_at` ascending. List responses include the four pagination fields `limit`, `offset`, `total_count`, and `has_more` in the envelope's `meta` block.

### 2.4. Common Resource Properties and Identifier Conventions

Every resource exposed by this API carries an `id` that is a server-minted UUID with no type prefix. Resources whose lifecycle requires update tracking — `Employee`, `I9Form`, and `EVerifyCase` — additionally carry `created_at`, `updated_at`, and `version`. Both `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits; `version` is an integer that begins at 1 on creation and increments by 1 on every mutation. `I9Document`, `ReverificationEvent`, `AuditEvent`, and `SystemClock` are leaf or system records that expose only `id` and `created_at` — they have neither `updated_at` nor `version`. Newly created resources are returned with HTTP status 201; reads and successful mutations of existing resources are returned with HTTP status 200.

### 2.5. Optimistic Concurrency Control

Any endpoint that mutates a `version`-bearing resource accepts an optional `version` integer in the request body. When the client supplies `version` and it does not match the server's current `version` for the target row, the request is rejected with `ERR_VERSION_CONFLICT`. When `version` is omitted from the body, the OCC check is skipped and the mutation is applied unconditionally to whatever the current row is — this is intentional for callers (such as system-driven retries) that explicitly accept last-writer-wins behaviour. Every successful mutation increments `version` by 1 and refreshes `updated_at` to the current `SystemClock.current_time`.

### 2.6. The Logical Clock and Federal Working Days

The API does not consult wall-clock time. All deadlines are measured against `SystemClock.current_time`, a single logical timestamp that is advanced only via an admin-only test-driving capability that accepts a target instant in the `to` field. This guarantees deterministic deadline arithmetic in tests and audits.

Several deadlines are measured in **federal working days**, which the system defines as Monday through Friday, excluding U.S. federal holidays cached in `SystemClock.federal_workdays_index`. When a deadline is described as "N federal working days after some date D", the count starts on the first federal working day strictly after D (D itself is not counted), advances one calendar day at a time, and increments the count each time the cursor lands on a federal working day; the deadline is then set to 23:59:59.999 UTC on the calendar date the cursor reaches when the count first equals N. Deadlines stored as a `datetime` are millisecond-precise; deadlines stored as a `date` (such as `reverification_due`) are at day granularity.

### 2.7. Nested Resource Path Resolution

Most endpoints are nested under `/employees/{employee_id}`. Path identifiers are validated left-to-right: the `Employee` is looked up first, then any `i9_form_id` or `case_id` segment is resolved within that employee's scope. If any segment fails to resolve, the response is `ERR_NOT_FOUND`; if a body field carrying a foreign-key reference such as `employee_id`, `i9_form_id`, `list_a_document_id`, `list_b_document_id`, `list_c_document_id`, or `supersedes_form_id` does not point at an existing row, the response is `ERR_REFERENCE_NOT_FOUND`. Both errors return HTTP 404 — the former is reserved for path-level lookups, the latter for body-level references.

### 2.8. The Audit Trail

Every state transition and every business-significant mutation produces an `AuditEvent`. Each row records `subject_employee_id` (the employee the event ultimately concerns, denormalized for query), `subject_entity` (one of `EMPLOYEE`, `I9_FORM`, `I9_DOCUMENT`, `EVERIFY_CASE`, or `REVERIFICATION_EVENT`), `subject_entity_id`, an `action` verb code (such as `SECTION_1_ATTEST`, `SECTION_2_SIGN`, `EVERIFY_SUBMIT`, `TNC_OPENED`, `TNC_CONTESTED`, `CASE_CLOSED`, `REVERIFY_OPENED`, `REVERIFY_RESOLVED`, `TERMINATE`), the `actor_role` (`Employee`, `HRStaff`, `EmployerRep`, or `System`), the `actor_user_id` (`X-User-ID` at the time of the action, or null when the actor is the system), and `occurred_at` (the server clock at action time). The audit trail is append-only; nothing in this API ever updates or deletes an `AuditEvent` row, and audit reads are ordered by `occurred_at` ascending.

### 2.9. Validation Priority Order

When a single request fails more than one rule, exactly one error is returned, chosen by priority from the following ordering: first, authentication headers must be present and well-formed (`ERR_AUTH_MISSING`); second, the role must be authorized for the endpoint (`ERR_FORBIDDEN`); third, every path identifier must resolve (`ERR_NOT_FOUND`); fourth, every body foreign-key reference must resolve (`ERR_REFERENCE_NOT_FOUND`); fifth, the target resource must be in a state from which the requested transition is permitted (`ERR_INVALID_STATE`); sixth, segregation of duties is enforced on Section 2 (`ERR_SEGREGATION_OF_DUTIES`); seventh through ninth, the Section 2 document list rule, document category match, and document expiry are checked in that order (`ERR_DOCUMENT_LIST_RULE`, then `ERR_DOCUMENT_CATEGORY_MISMATCH`, then `ERR_DOCUMENT_EXPIRED`); tenth, the TNC contest deadline is enforced on `tnc-decision`; eleventh, the Section 2 deadline is checked when `enforce_deadline` is supplied as true; twelfth, the constraint that at most one non-closed E-Verify case exists per employee; thirteenth, the idempotency-key replay check; fourteenth, form lineage rules; fifteenth, the STEM extension lateness rule; and sixteenth, pagination bounds. This ordering matters: a request that simultaneously violates an earlier and a later rule surfaces the earlier rule's `error_id`.

### 2.10. Concurrency and Idempotency Guarantees

Concurrent writes are serialized so that the database invariants are never violated by a race; in every contended scenario, exactly one writer wins and the other receives a deterministic error. Two simultaneous `POST` submissions of an E-Verify case for the same employee with the same `idempotency_key` result in exactly one row being created — the first writer wins on the `(employee_id, idempotency_key)` key, and the second request returns the same existing case row with HTTP 200 and `error_id` `ERR_IDEMPOTENT_REPLAY` semantics (the body carries the existing case). Two simultaneous submissions for the same employee with **different** `idempotency_key` values, when no case is currently open, serialize on E-Verify case creation per employee: one succeeds, the other is rejected with `ERR_CASE_ALREADY_OPEN` and HTTP 409. Two `EmployerRep` users signing Section 2 on the same form at the same moment serialize on `I9Form.form_status`: one succeeds; the other receives `ERR_FORM_ALREADY_SIGNED` with HTTP 409. Two `HRStaff` users creating the initial `I9Form` for the same employee at the same time serialize on the `(employee_id, form_kind)` pair where `form_kind` is `INITIAL`: one succeeds, the other is rejected with `ERR_DUPLICATE_INITIAL_FORM` and HTTP 409. When an employee posts a `tnc-decision` of `CONTEST` at the same instant the sweep attempts to close the case for deadline lapse, exactly one operation succeeds — if the employee's request serializes first the case transitions from `TNC` back to `PENDING` and the sweep is a no-op for that case, otherwise the case is closed by the sweep and the contest request is rejected with `ERR_TNC_DEADLINE_PASSED` and HTTP 409.

### 2.11. Automatic Sweep Capability

The deadline sweep is a system-driven, idempotent maintenance pass that the test harness can invoke explicitly. Each invocation walks all open work and applies two closures: any E-Verify case in state `TNC` whose `tnc_contest_deadline` is now in the past and whose `tnc_employee_decision` is still null is closed; any `ReverificationEvent` whose `resolved_at` is still null and whose `resolution_deadline` is now in the past is expired. Both closures cascade as described in §3, including termination of the affected employee.

## 3. Business Logic & Workflows

### 3.1. Creating an Employee Record and Anchoring the Three-Day Clock

Onboarding begins when `HRStaff` creates an `Employee` record. The request carries the employee's `legal_name` (a non-empty string of 1 to 200 characters after trimming), `date_of_birth` as an ISO 8601 date in YYYY-MM-DD form, `ssn` as exactly nine digits and unique across active employees, `citizenship_status` chosen from `US_CITIZEN`, `NON_CITIZEN_NATIONAL`, `LAWFUL_PERMANENT_RESIDENT`, or `ALIEN_AUTHORIZED`, and `start_date` — the first day of paid employment, which anchors every downstream deadline. Two optional fields accompany alien authorizations: `work_authorization_expiry` (an ISO 8601 date or null, required when `citizenship_status` is `ALIEN_AUTHORIZED` or when a `LAWFUL_PERMANENT_RESIDENT` carries an expiring card), and `visa_class` chosen from `F1_OPT`, `F1_OPT_STEM`, `H1B`, `L1`, `TN`, `OTHER`, or null.

On creation the system computes `section2_deadline`: the moment by which Section 2 must be signed. The rule is to count forward three federal working days from `start_date`, where `start_date` itself is excluded from the count even when it falls on a federal working day, then set the deadline to 23:59:59.999 UTC at the end of that third federal working day. The newly created employee starts with `is_terminated` false, `onboarding_status` `PENDING_SECTION_1`, and an `AuditEvent` whose `action` records the creation. If `HRStaff` subsequently corrects `start_date` through an employee update — a mutation that also accepts revisions to `visa_class` or `work_authorization_expiry` and which requires `version` in the request body for optimistic concurrency — and `start_date` is changed, `section2_deadline` is recomputed from the new value.

A read of an employee returns the record with its `onboarding_status` always re-derived (see §3.7) at read time. The list endpoint accepts filters by `onboarding_status` and `is_terminated`, in addition to standard `limit` and `offset` pagination.

### 3.2. Registering Identity Documents

Before Section 2 can be signed, the documents that satisfy the Form I-9 list rule must exist in the system. Either `HRStaff` or an `EmployerRep` may register a document against an employee, supplying `category` (`LIST_A`, `LIST_B`, or `LIST_C`), the canonical `document_title` (for example "U.S. Passport", "Permanent Resident Card", "EAD I-766", "Driver's License"), the `document_number` printed on the document, the `issuing_authority`, and optionally an `expiration_date` which is null only when the document is intrinsically non-expiring. A document may also be registered as a `receipt` — a temporary stand-in for a real document that has been lost, stolen, or damaged — by passing `receipt` as true. When a document is a receipt, the system computes `receipt_resolution_due` as the employee's `start_date` plus 90 calendar days; the actual document must replace the receipt by that date.

`I9Document` is a leaf record: it carries `id` and `created_at` but no `updated_at` or `version`. The list endpoint for an employee's documents accepts an optional `category` filter as well as standard pagination.

### 3.3. The I-9 Form Lifecycle: Section 1, Section 2, and Document Examination

`HRStaff` opens a new `I9Form` for an employee in state `DRAFT` by specifying `form_kind` — one of `INITIAL`, `REVERIFICATION`, or `REHIRE` — and, for the two non-initial kinds, a `supersedes_form_id` pointing to the prior form on the same employee. A `REVERIFICATION` form requires `supersedes_form_id` to resolve to a form in state `SECTION_2_DONE` on the same employee; a `REHIRE` form additionally requires the predecessor's `section2_completed_at` to be no earlier than three years before the new `start_date`. Lineage violations are rejected with `ERR_INVALID_FORM_LINEAGE`. An `INITIAL` form is unique per employee: a second concurrent `INITIAL` creation is rejected with `ERR_DUPLICATE_INITIAL_FORM`.

The employee then attests Section 1. This step is exclusive to the `Employee` role, and `X-User-ID` must equal the `Employee.id` — a non-owner Employee attempt is rejected with `ERR_FORBIDDEN`. The form's `form_kind` must be either `INITIAL` or `REHIRE`, or, for `REVERIFICATION`, the form referenced by `supersedes_form_id` must itself be in state `SECTION_2_DONE` on the same employee. The employee must not be terminated. On success the form transitions from `DRAFT` to `SECTION_1_DONE`: `section1_completed_at` is stamped with `SystemClock.current_time`, `section1_attested_by_user_id` is set to `X-User-ID`, `section2_deadline` is recomputed, an `AuditEvent` with `action` `SECTION_1_ATTEST` is appended, and `onboarding_status` moves to `PENDING_SECTION_2`. The request body carries only `version` for the OCC check.

Section 2 is the document-examination step and is exclusive to an `EmployerRep`. The form must be in state `SECTION_1_DONE`. Segregation of duties applies absolutely: the signing `X-User-ID` must differ from `section1_attested_by_user_id`; otherwise the request is rejected with `ERR_SEGREGATION_OF_DUTIES`. The `EmployerRep` references documents through `list_a_document_id`, `list_b_document_id`, and `list_c_document_id`. The list rule is: exactly one of `list_a_document_id` is set with both `list_b_document_id` and `list_c_document_id` null, **or** `list_a_document_id` is null while both `list_b_document_id` and `list_c_document_id` are set. Any other combination — `LIST_A` together with `LIST_B`, `LIST_A` together with `LIST_C`, `LIST_B` alone, `LIST_C` alone, or all three together — is rejected with `ERR_DOCUMENT_LIST_RULE`. Each referenced document must belong to the same `employee_id` as the form's path and its `category` must match the field that references it (the document in `list_a_document_id` must have `category` `LIST_A`, and likewise for the B and C fields), otherwise `ERR_DOCUMENT_CATEGORY_MISMATCH` is returned. Every referenced document must also be unexpired at `SystemClock.current_time`, with one carve-out: a document where `receipt` is true is accepted if and only if its `receipt_resolution_due` is strictly after the current time. A document with a non-null `expiration_date` strictly before the current time is rejected with `ERR_DOCUMENT_EXPIRED`.

The Section 2 request may include an optional `enforce_deadline` flag. When the flag is omitted or false, late Section 2 sign is permitted: the transition still executes, the form moves to `SECTION_2_DONE`, and an `AuditEvent` with action `SECTION_2_LATE` is appended alongside the regular Section 2 audit row to flag the lateness. When `enforce_deadline` is true and `SystemClock.current_time` is strictly later than the employee's `section2_deadline`, the request is rejected with `ERR_SECTION2_DEADLINE_MISSED`; on-time (current time equal to the deadline) is treated as still on time because the deadline timestamp is inclusive. On a successful transition the system stamps `section2_completed_at` with the current time, records `section2_completed_by_user_id` from `X-User-ID`, computes `reverification_due` (see §3.4), appends an `AuditEvent` whose `action` is `SECTION_2_SIGN`, and moves `onboarding_status` to `EVERIFY_PENDING`. If this newly-signed form has a `supersedes_form_id`, that predecessor form simultaneously transitions to state `SUPERSEDED` with its own `AuditEvent` of action `FORM_SUPERSEDED`, and any open `ReverificationEvent` whose `triggering_form_id` was the predecessor is resolved by setting its `resolved_at` to the new `section2_completed_at` and its `new_form_id` to the successor's `id`.

A form may also be voided by `HRStaff` while it is still in either `DRAFT` or `SECTION_1_DONE`. Voiding requires `version` in the request body. The transition from `DRAFT` to `VOIDED` has no further preconditions; the transition from `SECTION_1_DONE` to `VOIDED` additionally requires that no `EVerifyCase` has been opened against the form. Either way, an `AuditEvent` with action `FORM_VOIDED` is appended and the form's `form_status` becomes `VOIDED`. Voiding is not permitted after Section 2 has been signed; an attempt is rejected with `ERR_INVALID_STATE`. Both `SUPERSEDED` and `VOIDED` are terminal states. The list-forms endpoint accepts filters by `form_status` and `form_kind` alongside pagination.

### 3.4. Reverification Due Dates, OPT, and the STEM Extension

When Section 2 is signed, the system computes `reverification_due` — the date on which the employee's authorization to work, as established by this form, expires. Candidates for this date are gathered from three sources, then the system takes the smallest (earliest) of them: from the employee record, `work_authorization_expiry` when `citizenship_status` is `ALIEN_AUTHORIZED` and that field is non-null; from the form's documents, the `expiration_date` of each non-null Section 2 document whose `category` is `LIST_A` or `LIST_C` and whose `expiration_date` is non-null and is a reverification-bearing category; and, when `visa_class` is `F1_OPT` and the `LIST_A` document is an "EAD I-766", that document's `expiration_date` (the OPT EAD case). `LIST_B` identity-only documents are explicitly excluded from this minimum even when they carry an `expiration_date`. If no candidates exist, `reverification_due` is null. The result is at day granularity.

When `reverification_due` is non-null, the system creates a `ReverificationEvent` for the employee with `triggering_form_id` equal to the newly signed form, `reason` `WORK_AUTH_EXPIRY`, and a `resolution_deadline` computed by the reverification deadline rule below. This open event is the system's reminder that the employee must present new evidence on or before the due date.

The reverification deadline rule branches on the event's `reason`: for `WORK_AUTH_EXPIRY`, `resolution_deadline` is the triggering form's `reverification_due` itself at 23:59:59.999 UTC (reverification must be completed on or before the expiry); for `OPT_TO_OPT_STEM_EXTENSION`, `resolution_deadline` is the triggering form's `reverification_due` plus 180 calendar days, also at 23:59:59.999 UTC; and for `REHIRE_WITHIN_3_YEARS`, `resolution_deadline` follows the same federal-working-day arithmetic as the standard new-hire Section 2 deadline applied to the rehire's `start_date`.

The F-1 OPT STEM extension is a domain-specific automatic deadline shift. When `HRStaff` updates an employee whose existing `visa_class` is `F1_OPT` and the new `visa_class` is `F1_OPT_STEM`, the system performs two actions. First, the existing form's `reverification_due` is recomputed: instead of the original EAD `expiration_date`, the system uses that original date plus 180 calendar days, so no new I-9 form is required until the extended date. Second, a `ReverificationEvent` is opened with `reason` `OPT_TO_OPT_STEM_EXTENSION` and `resolution_deadline` set per the rule above. This update is only allowed while `SystemClock.current_time` is on or before the underlying EAD's `expiration_date`; an attempt to STEM-extend an already-lapsed authorization is rejected with `ERR_STEM_EXTENSION_LATE`. As with the standard rehire-deadline arithmetic, the rehire variant of the Section 2 deadline computes the later of the predecessor's `section2_completed_at` or three federal working days after the rehire `start_date`, allowing the employer to either reuse the prior I-9 or to start a new clock — whichever instant is later wins.

A `ReverificationEvent` is a leaf record: it carries `id` and `created_at` but no `updated_at` and no `version`. Each row records `employee_id`, `triggering_form_id`, `reason`, the eventual `new_form_id` once a successor `I9Form` resolves it, `resolution_deadline`, and `resolved_at`. The list-reverification-events endpoint accepts a `status` filter and standard `limit` / `offset`.

A `ReverificationEvent` begins in state `OPEN`. It transitions to `RESOLVED` when a successor `I9Form` whose `supersedes_form_id` equals this event's `triggering_form_id` reaches `SECTION_2_DONE` and the current time is on or before `resolution_deadline`; on resolution, the event's `resolved_at` is set to the successor's `section2_completed_at`, `new_form_id` is set to the successor's `id`, an `AuditEvent` with action `REVERIFY_RESOLVED` is appended, and the triggering form transitions to `SUPERSEDED`. It transitions to `EXPIRED` when, during a sweep, `resolved_at` is still null and the current time has passed `resolution_deadline`. Expiry appends an `AuditEvent` with action `REVERIFY_EXPIRED`, cascades into the employee-termination subroutine (`is_terminated` becomes true, an `AuditEvent` with action `TERMINATE` is appended), and moves `onboarding_status` to `NOT_AUTHORIZED`. Both `RESOLVED` and `EXPIRED` are terminal states.

### 3.5. The E-Verify Case: Submission, Branching Outcomes, and the TNC Window

Once a form is in state `SECTION_2_DONE`, an `EmployerRep` may submit an E-Verify case. The submission carries the `i9_form_id` and an `idempotency_key` — the latter required for retry safety. The case is created in state `DRAFT` and immediately transitions to `PENDING`. The submission has four preconditions: the linked form must be in state `SECTION_2_DONE`; `SystemClock.current_time` must be on or before `section2_completed_at` plus three federal working days (if `enforce_deadline` is supplied as true and the window has passed, the request is rejected with `ERR_EVERIFY_SUBMISSION_LATE`; otherwise the case is still recorded but a system audit flag captures the lateness); there must be no prior non-closed `EVerifyCase` for this employee, otherwise `ERR_CASE_ALREADY_OPEN`; and the `idempotency_key` must be unique across this employee's cases — a retry with the same key returns the existing case as a 200 OK rather than creating a duplicate. A submission stamps `submitted_at` with the current time, appends an `AuditEvent` whose `action` is `EVERIFY_SUBMIT`, and brings `onboarding_status` to `EVERIFY_PENDING`.

The E-Verify case carries `employee_id`, `i9_form_id`, `submitted_at`, `idempotency_key`, a `case_status` that is one of `DRAFT`, `PENDING`, `EMPLOYMENT_AUTHORIZED`, `TNC`, `FNC`, `CLOSED_AUTHORIZED`, or `CLOSED_NOT_AUTHORIZED`, a `tnc_kind` that is `SSA` or `DHS` or null, the `tnc_opened_at` instant, the `tnc_contest_deadline`, the employee's `tnc_employee_decision` of `CONTEST` or `NO_CONTEST` or null, and a `final_disposition` of `AUTHORIZED` or `NOT_AUTHORIZED` or null. The case is read via a single-case endpoint open to `EmployerRep`, `HRStaff`, and the owning `Employee`.

E-Verify result delivery is an `actor` `system` operation. The result payload carries `result` (one of `EMPLOYMENT_AUTHORIZED`, `TNC`, or `FNC`) and, for `TNC`, the `tnc_kind`. From `PENDING`, the case transitions to `EMPLOYMENT_AUTHORIZED` on result `EMPLOYMENT_AUTHORIZED`, to `TNC` on result `TNC`, or to `FNC` on result `FNC`. The `TNC` transition stamps `tnc_opened_at` with the current time, records the `tnc_kind` from the payload, computes `tnc_contest_deadline` as 10 federal working days after `tnc_opened_at` (the day of TNC issuance is not counted; the clock starts on the next federal working day and ends at 23:59:59.999 UTC on the calendar date of the tenth such day, millisecond-precise), appends an `AuditEvent` with action `TNC_OPENED`, and moves `onboarding_status` to `TNC_OPEN`. The `EMPLOYMENT_AUTHORIZED` transition appends an `AuditEvent` with action `CASE_AUTHORIZED`. The `FNC` transition appends an `AuditEvent` with action `FNC_RECEIVED`. Sibling result outcomes are symmetric: each branch is preconditioned on `case_status` being `PENDING`, each is actor `system`, and each produces an audit row.

The employee responds to a TNC through the `tnc-decision` endpoint. This action is exclusive to the `Employee` role, with `X-User-ID` matching the owning employee. The case must be in state `TNC` and the current time must be on or before `tnc_contest_deadline`; a request after the deadline is rejected with `ERR_TNC_DEADLINE_PASSED`. The decision is conveyed in the body's `decision` field. A `decision` of `CONTEST` records `tnc_employee_decision` as `CONTEST`, transitions the case from `TNC` back to `PENDING`, appends an `AuditEvent` with action `TNC_CONTESTED`, and moves `onboarding_status` back to `EVERIFY_PENDING` so the upstream agency can re-evaluate. A `decision` of `NO_CONTEST` records `tnc_employee_decision` as `NO_CONTEST`, sets `final_disposition` to `NOT_AUTHORIZED`, transitions the case to `CLOSED_NOT_AUTHORIZED`, appends an `AuditEvent` of action `CASE_CLOSED` with `disposition` `NOT_AUTHORIZED`, moves `onboarding_status` to `NOT_AUTHORIZED`, and cascades into the employee-termination subroutine (`is_terminated` becomes true and an additional `AuditEvent` with action `TERMINATE` is appended).

If a case in state `TNC` is left untouched until after `tnc_contest_deadline`, the next sweep closes it automatically. The sweep transitions the case from `TNC` to `CLOSED_NOT_AUTHORIZED` (precondition: `case_status` is `TNC` and `tnc_employee_decision` is still null), sets `final_disposition` to `NOT_AUTHORIZED`, appends an `AuditEvent` with action `TNC_DEADLINE_LAPSED` followed by an `AuditEvent` with action `CASE_CLOSED` and `disposition` `NOT_AUTHORIZED`, moves `onboarding_status` to `NOT_AUTHORIZED`, and cascades into the employee-termination subroutine described above (`is_terminated` becomes true with its own `AuditEvent` of action `TERMINATE`). The contest-versus-sweep race is serialized on `case_status` as described in §2.10.

### 3.6. Closing a Case and the Employer's Final Acknowledgement

An `EmployerRep` closes the case via the closure endpoint. From `EMPLOYMENT_AUTHORIZED` the case transitions to `CLOSED_AUTHORIZED`: `final_disposition` is set to `AUTHORIZED`, an `AuditEvent` with action `CASE_CLOSED` and `disposition` `AUTHORIZED` is appended, and `onboarding_status` moves to `AUTHORIZED`. From `FNC` the case transitions to `CLOSED_NOT_AUTHORIZED`: `final_disposition` is set to `NOT_AUTHORIZED`, an `AuditEvent` with action `CASE_CLOSED` and `disposition` `NOT_AUTHORIZED` is appended, `onboarding_status` moves to `NOT_AUTHORIZED`, and the employee-termination subroutine cascades (`is_terminated` becomes true with an `AuditEvent` of action `TERMINATE`). Closure from any other state is rejected as an invalid state transition. `CLOSED_AUTHORIZED` and `CLOSED_NOT_AUTHORIZED` are both terminal states for the E-Verify case state machine.

### 3.7. The Derived `onboarding_status` and How It Is Computed

Every read of an employee, and every write that touches a form's `form_status`, a case's `case_status`, a `ReverificationEvent.resolved_at`, or `Employee.is_terminated`, re-derives `onboarding_status` from scratch. The derivation is deterministic and proceeds as follows. If the employee's `is_terminated` is true, the status is `TERMINATED`. Otherwise the system identifies the employee's latest form — the `I9Form` for the employee with the most recent `created_at` whose `form_status` is not `SUPERSEDED` and not `VOIDED`, with ties broken by `id` ascending — and the latest non-closed case — the `EVerifyCase` for the employee with the most recent `created_at` whose `case_status` is not `CLOSED_AUTHORIZED` and not `CLOSED_NOT_AUTHORIZED`, again with ties broken by `id` ascending. If no such latest form exists, or the latest form's `form_status` is `DRAFT`, the status is `PENDING_SECTION_1`. If the latest form's `form_status` is `SECTION_1_DONE`, the status is `PENDING_SECTION_2`. Otherwise if no latest non-closed case exists, the status is `EVERIFY_PENDING` — Section 2 is done but no case is open yet. If a non-closed case exists and its `case_status` is `TNC`, the status is `TNC_OPEN`. If a non-closed case exists and its `case_status` is one of `PENDING`, `EMPLOYMENT_AUTHORIZED`, `FNC`, or `DRAFT`, the status is `EVERIFY_PENDING`. Otherwise, the system looks at the most recent closed case — the `EVerifyCase` for the employee whose `case_status` begins with `CLOSED_`, ordered by `created_at` descending with ties broken by `id` ascending — and reports `AUTHORIZED` when its `final_disposition` is `AUTHORIZED`, else `NOT_AUTHORIZED`.

The full set of `onboarding_status` values is therefore: `PENDING_SECTION_1`, `PENDING_SECTION_2`, `EVERIFY_PENDING`, `TNC_OPEN`, `AUTHORIZED`, `NOT_AUTHORIZED`, and `TERMINATED`.

## 4. Endpoint Definitions

The following table summarises every endpoint exposed by the API. All endpoints accept JSON request bodies and return JSON responses in the envelope described in §2.2. New resource creations return HTTP status code 201; reads, list operations, and successful state-changing mutations on existing resources return HTTP status code 200. The behavioural specification — request fields, side effects, and precondition errors — is given exclusively in §3 and §2; this table is a navigation aid, not a contract substitute.

| Method | Path | Description | Authorized Role(s) |
| --- | --- | --- | --- |
| POST | `/employees` | Create a new employee record in `PENDING_SECTION_1`. | `HRStaff` |
| GET | `/employees/{employee_id}` | Read an employee with derived `onboarding_status`. | `HRStaff`, `EmployerRep`, `Employee` |
| PATCH | `/employees/{employee_id}` | Update employee profile (start date correction, visa class change, work authorization expiry). | `HRStaff` |
| GET | `/employees` | List employees with filters. | `HRStaff`, `EmployerRep` |
| POST | `/employees/{employee_id}/i9-documents` | Register an identity document. | `HRStaff`, `EmployerRep` |
| GET | `/employees/{employee_id}/i9-documents` | List documents for an employee. | `HRStaff`, `EmployerRep`, `Employee` |
| POST | `/employees/{employee_id}/i9-forms` | Create a new I-9 form (initial, reverification, or rehire). | `HRStaff` |
| GET | `/employees/{employee_id}/i9-forms` | List forms for an employee. | `HRStaff`, `EmployerRep`, `Employee` |
| POST | `/employees/{employee_id}/i9-forms/{form_id}/section1` | Attest Section 1. | `Employee` |
| POST | `/employees/{employee_id}/i9-forms/{form_id}/section2` | Sign Section 2 with List A or List B+C documents. | `EmployerRep` |
| POST | `/i9-forms/{form_id}/void` | Void a draft or Section-1-done form. | `HRStaff` |
| POST | `/employees/{employee_id}/everify-cases` | Submit an E-Verify case (with `idempotency_key`). | `EmployerRep` |
| GET | `/everify-cases/{case_id}` | Read an E-Verify case. | `EmployerRep`, `HRStaff`, `Employee` |
| POST | `/everify-cases/{case_id}/result` | Deliver an E-Verify outcome (test/system hook). | `System` |
| POST | `/everify-cases/{case_id}/tnc-decision` | Employee responds to a TNC with `CONTEST` or `NO_CONTEST`. | `Employee` |
| POST | `/everify-cases/{case_id}/close` | Close an `EMPLOYMENT_AUTHORIZED` or `FNC` case. | `EmployerRep` |
| GET | `/employees/{employee_id}/reverification-events` | List reverification events for an employee. | `HRStaff`, `EmployerRep`, `Employee` |
| GET | `/employees/{employee_id}/audit-events` | Read the employee's append-only audit trail. | `HRStaff`, `EmployerRep`, `Employee` |
| POST | `/_clock/advance` | Test-only: advance the logical clock. | `System` |
| POST | `/_sweep/run` | Test-only: run the deadline sweep. | `System` |

## 5. Error Code Catalogue

The following table enumerates every error identifier returned by the API along with its HTTP status code. The triggering conditions are not listed here; they are described in narrative form in §2 and §3 near the workflows they guard.

| Error ID | HTTP Status Code |
| --- | --- |
| `ERR_AUTH_MISSING` | 401 |
| `ERR_FORBIDDEN` | 403 |
| `ERR_SEGREGATION_OF_DUTIES` | 403 |
| `ERR_NOT_FOUND` | 404 |
| `ERR_REFERENCE_NOT_FOUND` | 404 |
| `ERR_INVALID_STATE` | 409 |
| `ERR_FORM_ALREADY_SIGNED` | 409 |
| `ERR_DUPLICATE_INITIAL_FORM` | 409 |
| `ERR_INVALID_FORM_LINEAGE` | 422 |
| `ERR_DOCUMENT_LIST_RULE` | 422 |
| `ERR_DOCUMENT_CATEGORY_MISMATCH` | 422 |
| `ERR_DOCUMENT_EXPIRED` | 422 |
| `ERR_SECTION2_DEADLINE_MISSED` | 409 |
| `ERR_CASE_ALREADY_OPEN` | 409 |
| `ERR_IDEMPOTENT_REPLAY` | 200 |
| `ERR_TNC_DEADLINE_PASSED` | 409 |
| `ERR_EVERIFY_SUBMISSION_LATE` | 409 |
| `ERR_STEM_EXTENSION_LATE` | 422 |
| `ERR_VERSION_CONFLICT` | 409 |
| `ERR_PAGINATION` | 400 |
| `ERR_VALIDATION` | 422 |
