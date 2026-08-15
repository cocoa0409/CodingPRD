# Kosher & Halal Certification Agency API — Product Requirements Document

## 1. Introduction

A kosher and halal certification agency in the mold of the Orthodox Union or IFANCA sits at the intersection of religious law, food-safety operations, and commercial contracting. Its customers are food and ingredient manufacturers who need a recognized religious certificate on their packaging; its staff are reviewers, field supervisors (the mashgiach / murabbi corps), account managers, and certificate officers. The agency's reputation depends on two things: nothing certified may ever be out of compliance, and every deviation must be detected, recorded, remediated, and verified under segregation of duties.

This document specifies the REST API for that agency's operating platform. The system tracks a client from first contact (`PROSPECT`) through application, facility review, ingredient dossiers, product recipes, supervision visits (scheduled and unannounced), findings and remediation, annual agreements and invoices, and finally certificate issuance, seasonal windows, suspension, renewal, and withdrawal. Two design commitments run throughout: first, compliance state is always derivable from the ledger of findings and equipment status, never hand-edited; second, money moves on its own track — invoices and payments are segregated from certificate issuance so that no single operator can both collect a fee and grant the certificate it pays for.

The API is mounted under `/api`. All operations are authenticated by header-carried identity and role; a deterministic logical clock drives every deadline, expiry, and escalation in the system so that audits are reproducible.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request must carry two headers: `X-User-ID` and `X-User-Role`. A request missing either header, or carrying an `X-User-Role` value outside the six declared roles, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400). A request whose role is not permitted on the target endpoint is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403) — this includes an `AccountManager` attempting to schedule an `UNANNOUNCED` visit, which is exclusively a `CertificationReviewer` capability.

The six roles, spelled exactly as the API expects them, are `AgencyAdmin`, `AccountManager`, `CertificationReviewer`, `FieldSupervisor`, `CertificateOfficer`, and `ClientContact`.

Identity semantics differ by role. When `X-User-Role` is `ClientContact`, `X-User-ID` is the `id` of the acting `AgencyClient` itself; ownership checks on any client-owned resource — facilities, ingredients, products, product-ingredient junctions, findings raised at the client's facilities, holiday windows at the client's facilities — compare the resource's owning `client_id` to `X-User-ID`, and a mismatch is rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403). For the other five roles, `X-User-ID` is an opaque operator identifier not tied to any persisted entity. The server records it where a workflow requires attribution — `inspector_user_id` on a scheduled visit, `assigned_supervisor_id` on a confirmed holiday window, `paid_recorded_by` on a paid invoice — but it never compares those values to any entity's `id`. Assignment-scoped actions enforce the opaque id directly: a `FieldSupervisor` may start, complete, declare no-access on, or raise findings only on visits whose `inspector_user_id` equals `X-User-ID`, and may complete a holiday window only when its `assigned_supervisor_id` equals `X-User-ID`; violations are rejected with `ERR_NOT_ASSIGNED_INSPECTOR` (HTTP 403).

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

List endpoints accept two query parameters, `limit` and `offset`. The `limit` defaults to 10, must be at least 1, and may not exceed 100; the `offset` defaults to 0. List responses order results by `created_at` ascending. The `meta` envelope of every list response carries `limit`, `offset`, `total_count`, and `has_more`.

### 2.4. Common Resource Properties and the Logical Clock

Every persisted resource carries `id`, `created_at`, `updated_at`, and `version`. The `id` is a server-minted UUID with no type prefix. `created_at` and `updated_at` are ISO 8601 UTC timestamps with three fractional digits. `version` is an integer starting at creation and incremented on every mutation of the record; `updated_at` is refreshed on the same mutations. All entities in this system carry the full common set — there are no reduced-metadata entities.

The platform never consults wall-clock time. A logical clock, settable by an `AgencyAdmin` through an admin-only test-driving capability that advances the server's logical clock to a supplied `to_iso8601` instant, determines every deadline, expiry, and escalation. The startup default, before any set, is exactly 2026-08-01T00:00:00Z; once set, the clock never falls back to wall-clock. Setting the clock runs a deterministic five-step sweep in this exact order: (1) equipment lines whose `kosherization_state` is `VALID` and whose `kosherized_valid_until` is now in the past (strictly earlier than the new clock instant) transition to `EXPIRED`; (2) findings in `OPEN` or `REOPENED` whose `remediation_deadline` is now in the past escalate to `ESCALATED`, firing the facility → certificate → client cascade described in §3.6; (3) certificates in `ACTIVE` whose `valid_until` is now in the past transition to `EXPIRED` with the client recompute; (4) invoices in `ISSUED` whose `due_date` has passed transition to `OVERDUE`, and any `OVERDUE` invoice of type `ANNUAL_CERTIFICATION` or `RENEWAL` more than 14 days past its `due_date` suspends every `ACTIVE` certificate of that client, then recomputes the client; (5) agreements in `ACTIVE` whose `term_end_date` is now before the current date transition to `EXPIRED`.

### 2.5. Nested Resource Retrieval and Existence Checking

Paths that traverse a resource hierarchy — a facility's equipment lines, a facility's visits, a visit's findings, a product's junctions, an ingredient's usages, a certificate's entries, a facility's holiday windows — validate path identifiers left to right. A missing id at any level yields `ERR_NOT_FOUND` (HTTP 404); identifiers referenced inside a request body are validated after the path. One deliberate opacity rule applies: an `UNANNOUNCED` visit is treated as non-existent for any `ClientContact` caller — it is absent from their list responses and returns 404 on direct fetch — so that unannounced inspections remain genuinely unannounced.

### 2.6. Monetary Precision, Rounding, and Fee Arithmetic

All monetary values are integer cents. Wherever a fee calculation produces a fractional result, rounding is round-half-up, and the points at which rounding is applied are pinned by §3: per-line before summation on product-addition invoices, once at the scheme-multiplier step and once at the risk-surcharge step of the annual fee, and once on the volume-discount amount. Summing raw unrounded line amounts and rounding afterward is forbidden. Volume-discount tier selection keys on the pre-discount subtotal exactly once; the post-discount total never re-enters tier selection, even when subtracting the discount drops the total below the threshold that granted it.

### 2.7. Optimistic Concurrency on Agreement Creation

Exactly one endpoint participates in optimistic concurrency control: the creation of a `CertificationAgreement`. The request must carry `expected_client_version`, holding the client's `version` as the caller last observed it. If that value no longer matches the client's current `version` — because another writer has advanced the client record since the caller read it — the create is rejected with `ERR_STALE_CLIENT_VERSION` (HTTP 412), before any business logic runs. The check is a pure stale-version rejection; a second, strictly sequential create carrying the now-superseded version deterministically fails. No other endpoint takes a version field.

### 2.8. Validation Ordering

When several checks could reject the same request, the server applies them in a fixed priority order so the surfaced error is deterministic. First, header presence and role validity (`ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`), then request-body shape — required fields present, enum members legal, datetimes parseable, and for any time range the end strictly later than the start (`ERR_INVALID_REQUEST`). Next, role authorization (`ERR_FORBIDDEN_ROLE`), then ownership and assignment scope (`ERR_CLIENT_SCOPE_VIOLATION`, `ERR_NOT_ASSIGNED_INSPECTOR`). Existence checks follow (`ERR_NOT_FOUND`), then the optimistic-concurrency check on agreement creation (`ERR_STALE_CLIENT_VERSION`). Only then are entity-state gates evaluated (the family of `ERR_*_INVALID_STATE` errors), then business-safety compliance gates (documentation, open findings, equipment, segregation, risk), then cross-entity referential integrity, then temporal-window rules, then uniqueness and cardinality constraints, and finally fiscal gates: the paid-fee requirement (`ERR_CERTIFICATION_FEE_UNPAID`) is located before the issuance segregation-of-duties check (`ERR_SEGREGATION_OF_DUTIES_ISSUANCE`), so an issuer who also recorded the payment surfaces the segregation error only when a qualifying paid invoice exists at all.

### 2.9. Segregation of Duties

Two segregation walls are hard requirements. On the fiscal side, the `AccountManager` records payments and the `CertificateOfficer` issues certificates; issuance requires a fee invoice whose `paid_recorded_by` differs from the issuer's `X-User-ID`, else `ERR_SEGREGATION_OF_DUTIES_ISSUANCE` (HTTP 403). Since the officer role never records payments, this wall primarily blocks an operator holding both assignments under one identity. On the inspection side, a `FieldSupervisor` verifying a remediation must not be the same supervisor whose visit raised the finding; equality with the visit's `inspector_user_id` yields `ERR_SEGREGATION_OF_DUTIES_VERIFICATION` (HTTP 403).

## 3. Business Logic & Workflows

### 3.1. Client Onboarding and Lifecycle

An `AccountManager` registers a prospective client by supplying its `legal_name`, `certification_scheme`, and `contact_email`. The scheme is one of `KOSHER`, `HALAL`, or `DUAL`, and it scopes which agreement and certificate schemes are legal for this client for as long as the record lives: a `KOSHER` client may hold `KOSHER` agreements and certificates only, a `HALAL` client likewise, and a `DUAL` client may hold any of the three schemes. The new record starts as `PROSPECT` with `open_nc_score` zero, `risk_tier` `LOW`, and `total_billed_cents` zero.

From `PROSPECT`, the client itself — acting as a `ClientContact` whose `X-User-ID` equals the client's `id` — submits its certification application, moving to `APPLICANT`. Any attempt to submit from a status other than `PROSPECT` is rejected with `ERR_CLIENT_INVALID_STATE`, and a scope mismatch with `ERR_CLIENT_SCOPE_VIOLATION`. The transition from `APPLICANT` to `CERTIFIED` is never called directly: it happens as a bubble-up the first time one of the client's certificates reaches `ACTIVE` through issuance. Symmetrically, if every certificate of a `CERTIFIED` client leaves `ACTIVE` — by suspension, revocation, or expiry — the client bubble-up recompute moves the client to `SUSPENDED`; and when a certificate reinstate later restores an `ACTIVE` certificate to a `SUSPENDED` client, the client returns to `CERTIFIED`.

Withdrawal and termination are the two terminal exits. The client may withdraw itself from `PROSPECT`, `APPLICANT`, `CERTIFIED`, or `SUSPENDED`; the agency — through a `CertificateOfficer` — may terminate a client in any of those same four statuses. Both transitions move every certificate of the client that is in `DRAFT`, `ACTIVE`, or `SUSPENDED` into the terminal certificate state `REVOKED`, leaving already-terminal certificates untouched, and both land the client in its respective terminal state `WITHDRAWN` or `TERMINATED`, from which no transition exists. Acting on a client already in a terminal state, or in a status outside the allowed set, yields `ERR_CLIENT_INVALID_STATE`.

### 3.2. Facilities, Equipment Lines, and Kosherization

Facilities are registered by the client or by an `AccountManager` on the client's behalf, carrying `client_id`, `name`, `address`, and optionally `facility_role` — `OWNED` by default, or `CO_PACKER` for a contract packer site. A co-packer site both adds a per-site surcharge to the annual fee (§3.8) and, like any other site, cannot host certified production until its own initial visit has completed. New facilities start in `PENDING_REVIEW`.

Every production line at a facility is registered as an `EquipmentLine` with `facility_id` and a `designation` unique within that facility. A line carries two independent state dimensions that evolve in parallel on the same row. The first, `dedication_status`, begins `UNASSESSED` and is set once by a `CertificationReviewer` assessment to either `DEDICATED` (the line runs only certified product) or `SHARED` (the line is shared with non-certified production); assessing an already-assessed line is rejected with `ERR_EQUIPMENT_LINE_INVALID_STATE`, and assessment requires the hosting facility to be in `PENDING_REVIEW` or `APPROVED` (`ERR_FACILITY_INVALID_STATE`). The second dimension, `kosherization_state`, begins `NONE`. A shared line is never clean by default: if a line is assessed `SHARED` while its `kosherization_state` is `NONE`, that dimension immediately becomes `EXPIRED`.

A `FieldSupervisor` records a kosherization event on a line whose `kosherization_state` is `NONE`, `EXPIRED`, or `COMPROMISED`, provided the hosting facility is `APPROVED`; the line becomes `VALID` and its `kosherized_valid_until` is set to the event instant plus 72 hours. Kosherizing a line already `VALID` is rejected with `ERR_EQUIPMENT_LINE_INVALID_STATE`; the facility gate surfaces `ERR_FACILITY_INVALID_STATE`. The clock sweep expires validity: when the logical clock passes `kosherized_valid_until` — strictly later; at the exact instant the line is still `VALID` — the state becomes `EXPIRED`. A supervisor may also report a compromise (a non-certified run, a contamination event) on any line not already `COMPROMISED`, moving it from `NONE`, `VALID`, or `EXPIRED` to `COMPROMISED` and clearing `kosherized_valid_until` to null. While a line is `VALID`, `kosherized_valid_until` is populated; in every other state it is null.

Facility approval is the gateway to everything else. A `CertificationReviewer` approves a `PENDING_REVIEW` facility only when four conditions hold: at least one `INITIAL` supervision visit at this facility has reached `COMPLETED` (else `ERR_INITIAL_VISIT_REQUIRED`); no finding at this facility of severity `MAJOR` or `CRITICAL` is in `OPEN`, `REMEDIATION_SUBMITTED`, `REOPENED`, or `ESCALATED` (else `ERR_OPEN_MAJOR_FINDINGS`); every equipment line has a `dedication_status` other than `UNASSESSED` and a `kosherization_state` of `NONE` or `VALID` (else `ERR_EQUIPMENT_UNASSESSED`); and the facility is in fact still `PENDING_REVIEW` (else `ERR_FACILITY_INVALID_STATE`). A reviewer may suspend an `APPROVED` facility manually, and the system suspends it automatically as part of the critical-finding and no-access cascades (§3.6). Suspension cascades: every certificate whose `facility_ids` contains this facility and whose status is `ACTIVE` moves to `SUSPENDED`, and each client whose certificates were so suspended is recomputed — a `CERTIFIED` client left with zero `ACTIVE` certificates becomes `SUSPENDED`. Reinstating a `SUSPENDED` facility requires no open `MAJOR`/`CRITICAL` findings at the site and no line in `COMPROMISED` state; note that certificate and client reinstatement are deliberately not automatic — each certificate needs its own reinstate call afterward (§3.7).

The client decommissions a site it owns from `PENDING_REVIEW`, `APPROVED`, or `SUSPENDED` — other statuses yield `ERR_FACILITY_INVALID_STATE`, and a scope mismatch yields `ERR_CLIENT_SCOPE_VIOLATION`. Decommissioning removes the facility from the `facility_ids` of every certificate in `DRAFT`, `ACTIVE`, or `SUSPENDED`. A certificate whose scope becomes empty and which was `ACTIVE` moves to `SUSPENDED`; a `DRAFT` certificate simply keeps its now-empty scope, and an already-`SUSPENDED` certificate stays `SUSPENDED` with the reduced scope.

### 3.3. Ingredients, Change Notices, and the Re-Approval Cascade

A client submits an ingredient dossier with `client_id`, `name`, `manufacturer`, `source_category` — one of `ANIMAL`, `PLANT`, `MICROBIAL`, `MINERAL`, `SYNTHETIC` — and optionally `has_species_documentation` (default false). The dossier starts `SUBMITTED`. A `CertificationReviewer` starts the review (`SUBMITTED` → `UNDER_REVIEW`), then approves it (`UNDER_REVIEW` → `APPROVED`) or rejects it (`UNDER_REVIEW` → `REJECTED`). Approving an ingredient whose `source_category` is `ANIMAL` requires `has_species_documentation` to be true — species and slaughter documentation is mandatory for animal-derived approvals — else `ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED` (HTTP 422). Wrong-state calls surface `ERR_INGREDIENT_INVALID_STATE`.

The ingredient lifecycle is cyclic because suppliers change formulations. The client files a change notice on an `APPROVED` ingredient, carrying the free-text `change_summary`; the text is stored on the ingredient record (it is null until the first notice) and the ingredient moves to `CHANGE_PENDING`. That single filing fires a four-hop freeze cascade, all atomic within the request. Hop 1: every `ProductIngredient` junction referencing this ingredient with status `ACTIVE` flips to `PENDING_REAPPROVAL`. Hop 2: each product that owns a flipped junction and is currently `CERTIFIABLE` drops to `REVIEW_HOLD` — caused by the junction flip, not by the notice directly. Hop 3: each `CertificateProduct` entry whose product flipped in hop 2 and whose status is `INCLUDED` freezes to `FROZEN`. Hop 4: every certificate owning a frozen entry recomputes — `scope_status` becomes `PARTIAL_FROZEN`, and `active_product_count` is recomputed as the count of its `INCLUDED` entries.

The client then resubmits (`CHANGE_PENDING` → `UNDER_REVIEW`), and the reviewer decides again. Approval now runs the compensation cascade: every `PENDING_REAPPROVAL` junction for this ingredient returns to `ACTIVE`; each product whose junctions were restored, which is in `REVIEW_HOLD`, and which has no remaining junctions in `PENDING_REAPPROVAL` or `BLOCKED` returns to `CERTIFIABLE`; each `FROZEN` certificate entry for those restored products returns to `INCLUDED`; and each owning certificate recomputes `scope_status` (`FULL` when no `FROZEN` entries remain) and `active_product_count`. Rejection instead flips every `PENDING_REAPPROVAL` junction to `BLOCKED`, and affected products stay in `REVIEW_HOLD` until the client removes the blocked junction (§3.4). Both change-notice and resubmit are client-scope-checked against the ingredient's owning `client_id`.

### 3.4. Products, Recipes, and Certificate Listings

A client creates a product with `client_id`, `brand`, `name`, and an initial `ingredient_ids` list. Every listed ingredient must belong to the same client (else `ERR_CROSS_CLIENT_REFERENCE`) and must be `APPROVED` at link time (else `ERR_INGREDIENT_NOT_APPROVED`); the create builds one `ProductIngredient` junction per ingredient, each `ACTIVE`. The product starts `DRAFT`. Additional ingredients are linked one at a time by the client with a payload containing the `ingredient_id`, subject to the same same-client and `APPROVED` checks plus a no-duplicate rule — an ingredient that already has a non-`REMOVED` junction on this product is rejected with `ERR_DUPLICATE_PRODUCT_INGREDIENT`.

Submitting a product for review (`DRAFT` → `IN_REVIEW`) requires at least one junction in `ACTIVE` status; an empty recipe yields `ERR_PRODUCT_HAS_NO_INGREDIENTS` (HTTP 422). A `CertificationReviewer` then declares the product certification-eligible (`IN_REVIEW` → `CERTIFIABLE`) only when every `ACTIVE` junction links an ingredient whose status is `APPROVED` — otherwise `ERR_INGREDIENT_NOT_APPROVED`. `REVIEW_HOLD` is a system-only status, entered exclusively through the ingredient change-notice cascade, never by a direct call; it releases back to `CERTIFIABLE` automatically once zero junctions remain in `PENDING_REAPPROVAL` or `BLOCKED`, whether by re-approval compensation or by junction removal.

The client removes a junction from any product in `DRAFT`, `IN_REVIEW`, `REVIEW_HOLD`, or `CERTIFIABLE` — removal on a `WITHDRAWN` product yields `ERR_PRODUCT_INVALID_STATE`, and re-removing an already-`REMOVED` junction yields `ERR_PRODUCT_INGREDIENT_INVALID_STATE`. Removal is allowed from `ACTIVE`, `PENDING_REAPPROVAL`, or `BLOCKED` and always lands in `REMOVED`. If the product was in `REVIEW_HOLD` and the removal leaves no junctions in `PENDING_REAPPROVAL` or `BLOCKED`, the product returns to `CERTIFIABLE`, its `FROZEN` certificate entries return to `INCLUDED`, and the owning certificates recompute scope and count — this is the manual release valve for an ingredient that was rejected after a change notice.

Withdrawing a product (from `DRAFT`, `IN_REVIEW`, `CERTIFIABLE`, or `REVIEW_HOLD`) removes it from commerce: every `CertificateProduct` entry referencing it in `INCLUDED` or `FROZEN` becomes `REMOVED`, and each owning certificate recomputes `scope_status` and `active_product_count`. `WITHDRAWN` is terminal for products.

### 3.5. Supervision Visits and Unannounced Inspections

Visits are scheduled by an `AccountManager` or `CertificationReviewer` with `facility_id`, `visit_type`, `inspector_user_id`, `scheduled_start`, and `scheduled_end`. The visit type is `INITIAL`, `ROUTINE`, `UNANNOUNCED`, or `SPECIAL_HOLIDAY`; `UNANNOUNCED` visits may be created only by a `CertificationReviewer` — any other role, including `AccountManager`, is rejected with `ERR_FORBIDDEN_ROLE`. An `INITIAL` visit requires the facility to be in `PENDING_REVIEW`; the other types require only that the facility is not `DECOMMISSIONED`. The window end must be strictly after the start (`ERR_INVALID_REQUEST` otherwise). An inspector double-booking guard rejects the schedule with `ERR_INSPECTOR_SCHEDULE_CONFLICT` when the new visit intersects any `SCHEDULED` or `IN_PROGRESS` visit of the same inspector after expanding that existing visit by a two-hour travel buffer on both sides — formally, reject exactly when the new start is strictly earlier than the existing end plus two hours and the new end is strictly later than the existing start minus two hours. Both inequalities are strict, so a visit starting exactly at the existing end plus two hours is allowed. The new visit begins `SCHEDULED`.

The assigned inspector — and only the assigned inspector — starts the visit (`SCHEDULED` → `IN_PROGRESS`), and only while the current logical instant lies within the scheduled window inclusively on both ends; too early or too late yields `ERR_VISIT_WINDOW_NOT_ACTIVE`, a wrong state yields `ERR_VISIT_INVALID_STATE`, and a different supervisor yields `ERR_NOT_ASSIGNED_INSPECTOR`. Completion moves `IN_PROGRESS` → `COMPLETED` under the same assignment check. An `AccountManager` may cancel a `SCHEDULED` visit, moving it to `CANCELLED`.

When the inspector is refused entry or the site is dark, the inspector declares no-access from either `SCHEDULED` or `IN_PROGRESS`, landing in `NO_ACCESS`. That single declaration has heavy side effects, all atomic: an `InspectionFinding` is auto-created with severity `CRITICAL`, `origin` `AUTO_NO_ACCESS` (manually raised findings carry origin `MANUAL`), `status` `OPEN`, and a `remediation_deadline` exactly 7 days after the declaration instant; the client's `open_nc_score` is recomputed, rising by the critical weight of 8; if the facility was `APPROVED` it is suspended, which suspends in-scope `ACTIVE` certificates, which recomputes the client; and every equipment line at the facility is compromised, moving each line's `kosherization_state` to `COMPROMISED` and clearing its `kosherized_valid_until`.

### 3.6. Findings, Remediation, and the Nonconformance Score

While a visit is `IN_PROGRESS`, its assigned inspector raises findings with `severity` (`MINOR`, `MAJOR`, or `CRITICAL`), `description`, and a `remediation_deadline`. Each finding records its `visit_id`, and its `facility_id` is denormalized from the visit at creation. A new finding starts `OPEN` and immediately feeds the client's nonconformance bookkeeping: the client's `open_nc_score` is the sum of severity weights — `MINOR` weighs 1, `MAJOR` weighs 3, `CRITICAL` weighs 8 — over all findings at all of the client's facilities, of any facility status, whose finding status is `OPEN`, `REOPENED`, or `ESCALATED`. The client's `risk_tier` derives from the score: `LOW` when the score is at most 2, `MEDIUM` when it is from 3 through 7, and `HIGH` when it is 8 or more.

A `CRITICAL` finding raised manually fires the same cascade as a no-access declaration: an `APPROVED` hosting facility suspends, in-scope `ACTIVE` certificates suspend, the client recomputes, and all of the facility's equipment lines become `COMPROMISED`. The escalation path is time-driven instead: when the clock sweep finds an `OPEN` or `REOPENED` finding whose deadline has passed, the finding becomes `ESCALATED` and fires the facility → certificate → client suspension cascade (without the equipment compromise that only physical access events and critical observations cause).

The client responds to a finding in `OPEN`, `REOPENED`, or `ESCALATED` by submitting remediation with free-text `remediation_notes`, moving the finding to `REMEDIATION_SUBMITTED`; the score is recomputed because the finding has left the counted set. A `FieldSupervisor` then verifies, and the verifier must differ from the raising visit's `inspector_user_id` (else `ERR_SEGREGATION_OF_DUTIES_VERIFICATION`). Verifying with `outcome` `CLOSED` lands the finding in the terminal state `VERIFIED_CLOSED` — the score does not change on this transition because both `REMEDIATION_SUBMITTED` and `VERIFIED_CLOSED` are excluded from the counted set. Verifying with `outcome` `FAILED` requires a `new_remediation_deadline` strictly later than the current logical instant (else `ERR_INVALID_REQUEST`); the finding returns to `REOPENED`, its `remediation_deadline` is replaced, and the score recomputes upward by the finding's weight as it re-enters the counted set. Verifying a finding not in `REMEDIATION_SUBMITTED` is rejected with `ERR_FINDING_INVALID_STATE`.

### 3.7. Certificates: Issuance, Suspension, Renewal

A `CertificateOfficer` drafts a certificate with `client_id`, `scheme`, `term_type`, a multi-site `facility_ids` scope (mixing `OWNED` and `CO_PACKER` sites freely), and an initial `product_ids` list; for `term_type` `SEASONAL`, a `holiday_window_id` is required (its absence is `ERR_INVALID_REQUEST`) and the window's facility must be inside the scope, while for `ANNUAL` the field stays null. Every referenced facility and product must belong to the same client (`ERR_CROSS_CLIENT_REFERENCE`), and the scheme must be covered by the client's `certification_scheme` (`ERR_SCHEME_MISMATCH`). Drafting creates one `CertificateProduct` entry per listed product — each entry carries the owning certificate's `certificate_id` (system-set) and the referenced `product_id`, and starts `INCLUDED` — and sets `renews_certificate_id` to null (it is populated only on renewal children). The draft's `scope_status` computes as `FULL` — it is `PARTIAL_FROZEN` exactly when any entry is `FROZEN` — and `active_product_count` counts the `INCLUDED` entries; `issued_at` stays null until issuance.

Issuance (`DRAFT` → `ACTIVE`) is the most heavily gated transition in the system, and the gates are evaluated in this order. The certificate must be `DRAFT` (`ERR_CERTIFICATE_INVALID_STATE`). The client must be `APPLICANT` or `CERTIFIED` (`ERR_CLIENT_INVALID_STATE`). For a `SEASONAL` certificate, the linked holiday window must be `CONFIRMED` (`ERR_WINDOW_INVALID_STATE`). Every facility in scope must be `APPROVED` (`ERR_FACILITY_NOT_APPROVED`), and the scope must be non-empty (`ERR_CERTIFICATE_SCOPE_EMPTY`, HTTP 422). Every certificate entry must be `INCLUDED` and every listed product must be `CERTIFIABLE` (`ERR_PRODUCT_NOT_CERTIFIABLE`). An `ACTIVE` agreement must exist for the client (`ERR_NO_ACTIVE_AGREEMENT`) whose scheme covers the certificate's scheme (`ERR_SCHEME_MISMATCH`). Then the fiscal gate: for an initial certificate, an `ANNUAL_CERTIFICATION` invoice on that `ACTIVE` agreement must exist in `PAID` status; for a renewal child, a `RENEWAL` invoice with `related_certificate_id` naming this child must be `PAID`; failure is `ERR_CERTIFICATION_FEE_UNPAID` (HTTP 402). Finally the segregation wall: the paying invoice's `paid_recorded_by` must differ from the issuer's `X-User-ID` (else `ERR_SEGREGATION_OF_DUTIES_ISSUANCE`).

A successful issuance sets `issued_at` to the current logical instant and computes `valid_until` by term variant: an `ANNUAL` certificate is valid for exactly 365 days from `issued_at`; a `SEASONAL` certificate's `valid_until` is fixed to its holiday window's `window_end`, typically far shorter. A certificate is expired only when the current instant is strictly later than `valid_until`; at the exact instant it remains `ACTIVE`. Issuance also sets `scope_status` to `FULL`, recomputes `active_product_count`, supersedes the parent when `renews_certificate_id` is set (the renewed parent moves to `SUPERSEDED`), and bubbles the client up from `APPLICANT` to `CERTIFIED` on its first issuance.

An officer may suspend an `ACTIVE` certificate manually; suspension, revocation, and expiry all bubble up to recompute the client, dropping a `CERTIFIED` client with zero remaining `ACTIVE` certificates to `SUSPENDED`. Reinstatement (`SUSPENDED` → `ACTIVE`) requires every in-scope facility `APPROVED` (`ERR_FACILITY_NOT_APPROVED`), no findings of severity `MAJOR` or `CRITICAL` in `OPEN`, `REOPENED`, or `ESCALATED` on in-scope facilities (`ERR_OPEN_MAJOR_FINDINGS`), and no `OVERDUE` invoice anywhere on the client (`ERR_CERTIFICATION_FEE_UNPAID`). Downtime is never compensated: `valid_until` is unchanged by reinstatement. A successful reinstate bubbles a `SUSPENDED` client back to `CERTIFIED`. Revocation is allowed from `ACTIVE` or `SUSPENDED` (and, on the system cascade of client withdrawal or termination, from `DRAFT` as well) and is terminal, as are `EXPIRED` (clock sweep past `valid_until`) and `SUPERSEDED`.

Renewal operates on an `ACTIVE` `ANNUAL` certificate only — renewing a `SEASONAL` certificate yields `ERR_CERTIFICATE_NOT_RENEWABLE`, and renewing from any other state yields `ERR_CERTIFICATE_INVALID_STATE`. The renewal window is the sixty days before expiry: the current instant must be no earlier than `valid_until` minus 60 days and no later than `valid_until`, both bounds inclusive; outside the window the call is rejected with `ERR_RENEWAL_WINDOW_CLOSED`. Renewal is blocked while the client's `risk_tier` is `HIGH` (`ERR_CLIENT_HIGH_RISK`, HTTP 403), while any certificate entry is `FROZEN`, and while another renewal child of this certificate exists in `DRAFT`, `ACTIVE`, or `SUSPENDED` (`ERR_RENEWAL_ALREADY_EXISTS`). A successful renew creates a renewal-child `DRAFT` certificate whose `renews_certificate_id` names the parent, copying the parent's facilities and product list, and auto-creates the `RENEWAL` invoice (§3.8) with `related_certificate_id` pointing at the child. The child is then issued through the ordinary issuance flow — its fee gate looks for the `PAID` renewal invoice — and its own `valid_until`, set at its issuance, is the parent's `valid_until` plus 365 days.

Adding products to an `ACTIVE` certificate is atomic: the call names one or more `product_ids`, and any failure rejects the whole call. Each added product must belong to the same client, must be `CERTIFIABLE` (`ERR_PRODUCT_NOT_CERTIFIABLE`), and must not already be listed on this certificate in `INCLUDED` or `FROZEN` (`ERR_PRODUCT_ALREADY_CERTIFIED`). The call creates one `INCLUDED` entry per product, increments `active_product_count` accordingly, and auto-creates exactly one `PRODUCT_ADDITION` invoice with one prorated line per product in request order (§3.8). Removing an entry — from `INCLUDED` or `FROZEN` — moves it to `REMOVED`, decrements the certificate's `active_product_count`, and never refunds the addition fee; acting on an already-`REMOVED` entry yields `ERR_CERTIFICATE_PRODUCT_INVALID_STATE`.

### 3.8. Agreements, Fees, and Invoices

An `AccountManager` creates a `CertificationAgreement` for a client with `scheme`, `billing_cycle`, `term_start_date` (an ISO date, inclusive), `per_product_fee_cents`, and the OCC field `expected_client_version` (§2.7). The scheme must be covered by the client's `certification_scheme` (`ERR_SCHEME_MISMATCH`). The billing cycle is `ANNIVERSARY` or `CALENDAR_YEAR` and fixes `term_end_date` at creation: an anniversary agreement ends the day before the twelve-month anniversary of its start, while a calendar-year agreement ends on December 31 of the start year. On successful creation, any previously `ACTIVE` agreement of the same client moves to `SUPERSEDED` — a legitimate, spec-allowed replacement — and the client's `version` increments by 1, which is precisely why the create is OCC-guarded: a writer whose last-observed client version no longer matches has a stale view of which agreement is active and of the fee-relevant counters. The new agreement starts `DRAFT` with `annual_fee_snapshot_cents` null.

Activation (`DRAFT` → `ACTIVE`) requires the client to be `APPLICANT` or `CERTIFIED` (`ERR_CLIENT_INVALID_STATE`), the agreement still `DRAFT` (`ERR_AGREEMENT_INVALID_STATE`), and no other `ACTIVE` agreement for the client (`ERR_ACTIVE_AGREEMENT_EXISTS`). Activation freezes the annual fee onto `annual_fee_snapshot_cents` using the activation-snapshot variant of the fee calculation: later facility registrations or risk-tier movements never mutate the snapshot. The annual certification fee counts every facility of the client that is not `DECOMMISSIONED` — `PENDING_REVIEW`, `APPROVED`, and `SUSPENDED` sites all bill — ordered by `created_at` ascending so the earliest-created site is facility number one. The tiered base charges 120000 cents for the first facility, 90000 cents for each of the second through fifth facilities (the count of facilities from 2 up to at most 5), and 70000 cents for each facility beyond the fifth. A co-packer surcharge of 25000 cents is added per facility whose `facility_role` is `CO_PACKER`. The scheme multiplier is 1.0 for `KOSHER` or `HALAL` and 1.8 for `DUAL`, applied to the base and rounded half-up to integer cents. Finally a risk surcharge keyed on the client's `risk_tier` at the calculation instant — zero percent for `LOW`, five percent for `MEDIUM`, fifteen percent for `HIGH` — is applied to the rounded subtotal, itself rounded half-up, and added. The renewal-recompute variant runs the identical formula at renewal time against the then-current facility set and risk tier, so the renewal invoice may diverge from the frozen snapshot.

Every invoice carries an `invoice_type` naming one of four values. `ANNUAL_CERTIFICATION` invoices are created by an `AccountManager` against an `agreement_id` naming an `ACTIVE` agreement; the amount is the agreement's frozen `annual_fee_snapshot_cents`, and at most one non-`VOID` annual invoice may exist per agreement (a second attempt yields `ERR_DUPLICATE_ANNUAL_INVOICE`). `REINSTATEMENT` invoices are also manager-created, carry no `agreement_id`, are allowed only while the client is `SUSPENDED` (`ERR_CLIENT_INVALID_STATE` otherwise), and charge a flat 50000 cents. `PRODUCT_ADDITION` and `RENEWAL` invoices are never created directly — attempting to pass either type to the create call is rejected with `ERR_INVALID_REQUEST`; they are auto-created by the certificate add-products and renew flows respectively, with `agreement_id` system-set to the client's active agreement and, on renewals, `related_certificate_id` set to the renewal child. Every invoice's `due_date` is its creation instant plus 30 days, and `paid_recorded_by` is null while unpaid.

The product-addition invoice totals as follows. Each product's line is prorated forward-looking: the cycle end is the active agreement's `term_end_date` under an `ANNIVERSARY` cycle, or December 31 of the addition year under a `CALENDAR_YEAR` cycle — so identical inputs price differently whenever the term end is not December 31. Days remaining are the calendar days from the addition date up to but not including the cycle end date, floored at zero. The raw line amount is `per_product_fee_cents` multiplied by days remaining and divided by 365; each line is rounded half-up to integer cents individually, and `subtotal_cents` is the sum of the rounded lines — summing first and rounding once is forbidden. A volume discount then applies exactly once, keyed on the pre-discount subtotal: ten percent when the subtotal is at least 200000 cents, five percent when at least 100000 cents, otherwise zero, with the discount amount itself rounded half-up; `discount_cents` defaults to zero when no tier applies. The post-discount total never re-enters tier selection. `total_cents` is the subtotal minus the discount. A zero-total invoice — possible when nothing remains to bill — is created directly in `PAID` status with `paid_recorded_by` set to the literal string `system`.

Invoices begin `ISSUED`. An `AccountManager` records payment against an `ISSUED` or `OVERDUE` invoice, moving it to `PAID` and stamping `paid_recorded_by` with the manager's `X-User-ID`; payment or void against a `PAID` or `VOID` invoice yields `ERR_INVOICE_INVALID_STATE`. Voiding an `ISSUED` or `OVERDUE` invoice compensates the ledger. The client's `total_billed_cents` is the sum of `total_cents` over all of the client's invoices in `ISSUED`, `OVERDUE`, or `PAID` — `VOID` is excluded — recomputed whenever an invoice is created or voided. The clock sweep moves an `ISSUED` invoice past its `due_date` to `OVERDUE`, and an `OVERDUE` `ANNUAL_CERTIFICATION` or `RENEWAL` invoice more than 14 days past its `due_date` suspends every `ACTIVE` certificate of the client and recomputes the client — unpaid fees eventually pull the certificates.

### 3.9. Holiday Production Windows

Holiday and seasonal runs need dedicated supervision. A client requests a `HolidayProductionWindow` with `facility_id`, `holiday_code`, `window_start`, and `window_end`. The holiday code is one of `PASSOVER`, `ROSH_HASHANAH`, `RAMADAN`, or `EID_AL_FITR`; the first two require scheme coverage by a `KOSHER` or `DUAL` certificate, the latter two by `HALAL` or `DUAL`. The window end must be strictly after its start. Requests are half-open intervals — the start instant is included, the end instant excluded — and a new request is rejected with `ERR_WINDOW_OVERLAP` when its half-open interval intersects any `REQUESTED` or `CONFIRMED` window at the same facility; touching endpoints, where one window's end equals the other's start, do not intersect and are allowed. The request begins `REQUESTED` with `assigned_supervisor_id` null.

A `CertificationReviewer` confirms a `REQUESTED` window, supplying the `assigned_supervisor_id` that is then fixed on the record. Confirmation requires the hosting facility `APPROVED` (`ERR_FACILITY_NOT_APPROVED`); a covering certificate — some `ACTIVE` certificate whose `facility_ids` contains this facility and whose scheme covers the holiday code (`ERR_NO_COVERING_CERTIFICATE`); and a conflict check for the supervisor: the assignment is rejected with `ERR_SUPERVISOR_WINDOW_CONFLICT` when this window, expanded by 24 hours on both sides, would intersect any other `CONFIRMED` window of the same supervisor at any facility, similarly expanded — formally, reject exactly when this window's start is strictly earlier than the other window's end plus 24 hours and this window's end is strictly later than the other window's start minus 24 hours. Both inequalities are strict, so a window starting exactly at another's end plus 24 hours is allowed. The assigned supervisor — and only that supervisor — completes the window (`CONFIRMED` → `COMPLETED`), and not before `window_end`; earlier completion yields `ERR_VISIT_WINDOW_NOT_ACTIVE`, and a wrong-state call yields `ERR_WINDOW_INVALID_STATE`. Either the owning client or a reviewer may cancel a window in `REQUESTED` or `CONFIRMED`, moving it to `CANCELLED`, except while a certificate in `DRAFT`, `ACTIVE`, or `SUSPENDED` references it via `holiday_window_id`, which blocks cancellation with `ERR_WINDOW_REFERENCED_BY_CERTIFICATE`.

## 4. Endpoint Definitions

New resources are returned with status 201; modifications to existing resources and action transitions return 200. The table below is a navigation index only — request fields, side effects, and gating conditions are specified in §2 and §3.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /api/_clock/set_current_utc | Advance the logical clock and run the five-step sweep | AgencyAdmin |
| POST | /api/clients | Register a prospective client | AccountManager |
| GET | /api/clients | List clients with pagination | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/clients/{id} | Get one client | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/clients/{id}/submit-application | Client submits its application | ClientContact |
| POST | /api/clients/{id}/withdraw | Client withdraws; live certificates revoked | ClientContact |
| POST | /api/clients/{id}/terminate | Agency terminates the client; live certificates revoked | CertificateOfficer |
| POST | /api/facilities | Register a facility | ClientContact, AccountManager |
| GET | /api/facilities | List facilities | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/facilities/{id} | Get one facility | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/facilities/{id}/approve | Approve facility after review gates | CertificationReviewer |
| POST | /api/facilities/{id}/suspend | Manually suspend a facility; cascades | CertificationReviewer |
| POST | /api/facilities/{id}/reinstate | Reinstate a suspended facility | CertificationReviewer |
| POST | /api/facilities/{id}/decommission | Decommission a site; shrinks certificate scopes | ClientContact |
| POST | /api/equipment-lines | Register a production line | ClientContact, AccountManager |
| GET | /api/equipment-lines/{id} | Get one equipment line | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/facilities/{id}/equipment-lines | List a facility's equipment lines | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/equipment-lines/{id}/assess | Set dedication status | CertificationReviewer |
| POST | /api/equipment-lines/{id}/kosherization-events | Record a kosherization event | FieldSupervisor |
| POST | /api/equipment-lines/{id}/report-compromise | Report a line compromise | FieldSupervisor |
| POST | /api/ingredients | Submit an ingredient dossier | ClientContact |
| GET | /api/ingredients | List ingredients | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/ingredients/{id} | Get one ingredient | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/ingredients/{id}/product-usages | List junctions referencing this ingredient | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/ingredients/{id}/start-review | Begin ingredient review | CertificationReviewer |
| POST | /api/ingredients/{id}/approve | Approve ingredient; runs compensation cascade | CertificationReviewer |
| POST | /api/ingredients/{id}/reject | Reject ingredient; blocks pending junctions | CertificationReviewer |
| POST | /api/ingredients/{id}/change-notices | File a change notice; fires freeze cascade | ClientContact |
| POST | /api/ingredients/{id}/resubmit | Resubmit after a change notice | ClientContact |
| POST | /api/products | Create a product with its initial recipe | ClientContact |
| GET | /api/products | List products | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/products/{id} | Get one product | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/products/{id}/ingredients | List a product's junctions | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/products/{id}/certificate-listings | List certificate entries referencing this product | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/products/{id}/ingredients | Add one ingredient to the recipe | ClientContact |
| DELETE | /api/product-ingredients/{id} | Remove a junction | ClientContact |
| POST | /api/products/{id}/submit-review | Submit product for review | ClientContact |
| POST | /api/products/{id}/certify-eligible | Declare product certification-eligible | CertificationReviewer |
| POST | /api/products/{id}/withdraw | Withdraw a product | ClientContact |
| POST | /api/visits | Schedule a visit | AccountManager, CertificationReviewer |
| GET | /api/visits | List visits | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/visits/{id} | Get one visit | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/facilities/{id}/visits | List a facility's visits | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/visits/{id}/start | Start an assigned visit inside its window | FieldSupervisor |
| POST | /api/visits/{id}/complete | Complete an assigned visit | FieldSupervisor |
| POST | /api/visits/{id}/no-access | Declare no access; fires cascade | FieldSupervisor |
| POST | /api/visits/{id}/cancel | Cancel a scheduled visit | AccountManager |
| POST | /api/visits/{id}/findings | Raise a finding during a visit | FieldSupervisor |
| GET | /api/visits/{id}/findings | List a visit's findings | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/findings | List findings | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/findings/{id} | Get one finding | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/findings/{id}/submit-remediation | Submit remediation for a finding | ClientContact |
| POST | /api/findings/{id}/verify | Verify remediation (closed or failed) | FieldSupervisor |
| POST | /api/agreements | Create an agreement (OCC-guarded) | AccountManager |
| GET | /api/agreements | List agreements | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/agreements/{id} | Get one agreement | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/agreements/{id}/activate | Activate an agreement; freezes the fee snapshot | AccountManager |
| POST | /api/invoices | Issue an annual-certification or reinstatement invoice | AccountManager |
| GET | /api/invoices | List invoices | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/invoices/{id} | Get one invoice | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/invoices/{id}/record-payment | Record payment on an invoice | AccountManager |
| POST | /api/invoices/{id}/void | Void an invoice | AccountManager |
| POST | /api/certificates | Create a draft certificate with scope and products | CertificateOfficer |
| GET | /api/certificates | List certificates | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/certificates/{id} | Get one certificate | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/certificates/{id}/products | List a certificate's entries | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/certificates/{id}/issue | Issue a certificate under the full gate chain | CertificateOfficer |
| POST | /api/certificates/{id}/products | Add products to an active certificate; auto-invoices | CertificateOfficer |
| DELETE | /api/certificate-products/{id} | Remove a certificate entry | CertificateOfficer |
| POST | /api/certificates/{id}/suspend | Suspend a certificate | CertificateOfficer |
| POST | /api/certificates/{id}/reinstate | Reinstate a suspended certificate | CertificateOfficer |
| POST | /api/certificates/{id}/revoke | Revoke a certificate | CertificateOfficer |
| POST | /api/certificates/{id}/renew | Create a renewal child and its invoice | CertificateOfficer |
| POST | /api/holiday-windows | Request a seasonal production window | ClientContact |
| GET | /api/holiday-windows/{id} | Get one window | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| GET | /api/facilities/{id}/holiday-windows | List a facility's windows | AgencyAdmin, AccountManager, CertificationReviewer, FieldSupervisor, CertificateOfficer, ClientContact |
| POST | /api/holiday-windows/{id}/confirm | Confirm a window and assign its supervisor | CertificationReviewer |
| POST | /api/holiday-windows/{id}/complete | Complete a confirmed window | FieldSupervisor |
| POST | /api/holiday-windows/{id}/cancel | Cancel a window not referenced by a live certificate | ClientContact, CertificationReviewer |

## 5. Error Code Catalogue

Trigger conditions for every error are specified in §2 and §3; this table is the enumeration of identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER | 400 |
| ERR_INVALID_REQUEST | 400 |
| ERR_FORBIDDEN_ROLE | 403 |
| ERR_CLIENT_SCOPE_VIOLATION | 403 |
| ERR_NOT_ASSIGNED_INSPECTOR | 403 |
| ERR_SEGREGATION_OF_DUTIES_VERIFICATION | 403 |
| ERR_SEGREGATION_OF_DUTIES_ISSUANCE | 403 |
| ERR_CLIENT_HIGH_RISK | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_STALE_CLIENT_VERSION | 412 |
| ERR_CLIENT_INVALID_STATE | 409 |
| ERR_FACILITY_INVALID_STATE | 409 |
| ERR_INGREDIENT_INVALID_STATE | 409 |
| ERR_PRODUCT_INVALID_STATE | 409 |
| ERR_PRODUCT_INGREDIENT_INVALID_STATE | 409 |
| ERR_VISIT_INVALID_STATE | 409 |
| ERR_FINDING_INVALID_STATE | 409 |
| ERR_AGREEMENT_INVALID_STATE | 409 |
| ERR_INVOICE_INVALID_STATE | 409 |
| ERR_CERTIFICATE_INVALID_STATE | 409 |
| ERR_CERTIFICATE_PRODUCT_INVALID_STATE | 409 |
| ERR_WINDOW_INVALID_STATE | 409 |
| ERR_EQUIPMENT_LINE_INVALID_STATE | 409 |
| ERR_ANIMAL_SOURCE_DOCUMENTATION_REQUIRED | 422 |
| ERR_INITIAL_VISIT_REQUIRED | 409 |
| ERR_OPEN_MAJOR_FINDINGS | 409 |
| ERR_EQUIPMENT_UNASSESSED | 409 |
| ERR_FACILITY_NOT_APPROVED | 409 |
| ERR_PRODUCT_NOT_CERTIFIABLE | 409 |
| ERR_NO_COVERING_CERTIFICATE | 409 |
| ERR_CROSS_CLIENT_REFERENCE | 422 |
| ERR_INGREDIENT_NOT_APPROVED | 409 |
| ERR_PRODUCT_ALREADY_CERTIFIED | 409 |
| ERR_DUPLICATE_PRODUCT_INGREDIENT | 409 |
| ERR_SCHEME_MISMATCH | 422 |
| ERR_NO_ACTIVE_AGREEMENT | 409 |
| ERR_VISIT_WINDOW_NOT_ACTIVE | 409 |
| ERR_RENEWAL_WINDOW_CLOSED | 409 |
| ERR_WINDOW_OVERLAP | 409 |
| ERR_INSPECTOR_SCHEDULE_CONFLICT | 409 |
| ERR_SUPERVISOR_WINDOW_CONFLICT | 409 |
| ERR_ACTIVE_AGREEMENT_EXISTS | 409 |
| ERR_RENEWAL_ALREADY_EXISTS | 409 |
| ERR_CERTIFICATE_SCOPE_EMPTY | 422 |
| ERR_PRODUCT_HAS_NO_INGREDIENTS | 422 |
| ERR_WINDOW_REFERENCED_BY_CERTIFICATE | 409 |
| ERR_CERTIFICATE_NOT_RENEWABLE | 409 |
| ERR_DUPLICATE_ANNUAL_INVOICE | 409 |
| ERR_CERTIFICATION_FEE_UNPAID | 402 |
