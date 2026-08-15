# University Bookstore Course Materials API — Product Requirements Document

## 1. Introduction

A university bookstore operation lives and dies by the academic calendar. Faculty must declare which titles their sections will use before a federally driven price-transparency deadline; the store must then decide how many new, used, rental, and digital copies to bring in, against a term-level purchasing budget; students buy or rent against financial-aid windows; unsold inventory flows back out through buyback at the end of term; and publishers owe the institution a commission on net sales. Each of these steps has its own clock, its own money arithmetic, and its own failure modes, and each one feeds the next: an adoption that misses its deadline changes a section's compliance standing, which in turn gates whether commission may be issued to the institution at all.

This document specifies the REST API that backs that operation, mounted under `/bookstore`. It covers academic-term orchestration, the publisher catalog and deal agreements, course sections and enrollments, faculty adoptions with their review loop, buy-plan commitment and receipt, student order placement with aid tendering, returns and refunds, inclusive-access billing with opt-out handling, end-of-term buyback with dual-variant pricing, and commission statements with segregation of duties. The API is consumed by five distinct operator populations, and the rules below are written so that a reader can reconstruct the complete behavioral contract — every threshold, every cascade, every rejection — from the prose alone.

## 2. Global Specifications & System-Wide Principles

### 2.1. User and Role-Based Access Control

Every request carries two headers: `X-User-ID` and `X-User-Role`. If either header is missing, or the role value is not one of the declared roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401). If the role is recognized but is not permitted on the target endpoint, the request is rejected with `ERR_FORBIDDEN` (HTTP 403). Where an endpoint is owner-scoped and the acting entity does not own the target resource, the rejection is `ERR_NOT_OWNER` (HTTP 403).

The declared roles, spelled exactly as the header value must appear, are:

- `PlatformAdmin` — configures terms, publishers, agreements, titles, faculty, students, sections, wholesale quotes, enrollments, and the test-driving clock. When `X-User-Role` is `PlatformAdmin`, `X-User-ID` is an opaque operator identifier not tied to any persisted entity; the server does not compare it to any entity's `id`.
- `BookstoreManager` — operates the store day to day: reviews and approves adoptions, edits and commits buy plans, locks sections, advances the term through its operational phases, processes returns with override authority, refunds inclusive-access charges, and pays or rejects buyback tickets. When `X-User-Role` is `BookstoreManager`, `X-User-ID` is an opaque operator identifier; the server records it where a workflow captures an actor (for example `committed_by_user_id` on a committed buy plan) but does not compare it to any entity's `id`.
- `FinanceAdmin` — the bursar's office: adjusts student aid awards and drives the commission-statement lifecycle, deliberately segregated from buy-plan committers. When `X-User-Role` is `FinanceAdmin`, `X-User-ID` is an opaque operator identifier; the server records it as `issued_by_user_id` when a statement is issued but does not compare it to any entity's `id`.
- `Faculty` — an instructor who owns adoptions for their own sections. When `X-User-Role` is `Faculty`, `X-User-ID` is the `id` of the acting `Faculty` record; ownership checks on an adoption compare the adoption's `faculty_id` (copied from the section at creation) to `X-User-ID`.
- `Student` — a buyer and seller who owns orders, inclusive-access charges, buyback tickets, and pre-lock enrollment drops. When `X-User-Role` is `Student`, `X-User-ID` is the `id` of the acting `Student` record; ownership checks compare the resource's `student_id` field to `X-User-ID`. On student-scoped creation endpoints (order placement, buyback-ticket creation), an `X-User-ID` that matches no persisted `Student` record is rejected with `ERR_NOT_FOUND` (HTTP 404).

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
- The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits, taken from the logical clock of §2.5 (never the wall clock).
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

List endpoints accept the query parameters `limit` and `offset`. The `limit` defaults to 10, with a minimum of 1 and a maximum of 100, and the `offset` defaults to 0; out-of-range values are clamped into range rather than rejected (a `limit` below 1 becomes 1, above 100 becomes 100, and a negative `offset` becomes 0), while a non-integer `limit` or `offset` is rejected with `ERR_VALIDATION`. Results are sorted by `created_at` ascending, with ties preserving insertion (creation) order. The `meta` block of a list response carries `limit`, `offset`, `total_count`, and `has_more`, so a client can page deterministically through any collection.

### 2.4. Common Resource Properties

Every persisted resource carries a server-minted `id` (a UUID with no type prefix), a `created_at` timestamp, an `updated_at` timestamp, and an integer `version`. Both timestamps are ISO 8601 UTC with three fractional digits; `updated_at` refreshes on every mutation. The `version` starts at 1 on creation and increments by exactly one on every mutation of that resource — including mutations caused by cascades. There are no exceptions in this domain: all entities, including `OrderLine` and `InclusiveAccessCharge`, carry the full common field set. The `version` field is the linchpin of optimistic concurrency control (§2.7) and of audit narratives throughout §3. All state is held in memory only: the store starts empty on every server boot, and every entity comes into existence exclusively through the API surface of §4.

### 2.5. Logical Time and the Test-Driving Clock

All temporal rules in this document are evaluated against a server-side logical clock, never the wall clock. Before any clock call, the logical time defaults to 2026-05-01T00:00:00Z. A `PlatformAdmin`-only test-driving capability sets the logical clock to a supplied `to_iso8601` instant; from then on, every deadline comparison, window check, timestamp stamp, and quote expiry uses that logical time. The clock never falls back to wall-clock time. Whenever this document says "now", it means the current logical time. Any ISO 8601 datetime supplied in a request body without an explicit UTC offset is interpreted as UTC.

### 2.6. Monetary Representation, Precision, and Rounding

All money is integer cents. Every calculated price, cost, refund, or commission that involves multiplication by a fractional percentage is rounded half-up to the nearest integer cent at the step where the scaffold of the calculation says so — per order line before any cap is applied for shelf pricing, per override refund for returns, per title for commissions, per committed plan for landed cost, and per buyback offer. Percentages such as a publisher's `discount_pct`, `digital_discount_pct`, and `commission_pct` are stored as decimal fractions that must be at least 0 and strictly less than 1.

### 2.7. Optimistic Concurrency Control

Four write operations require the caller to prove it has observed the current state of a parent entity before writing. Each takes a non-optional expected-version field; if the supplied value does not equal the parent entity's current `version`, the request is rejected with `ERR_STALE_VERSION` (HTTP 412). The version check runs after existence and from-state checks, before any business-rule evaluation. Endpoints not listed here do not take a version field.

- Updating an adoption (the quantity/price edit and revision-loop operation) requires `expected_adoption_version` matching the adoption's current `version`. A client whose quantities and posted price derive from an older read is rejected rather than allowed to overwrite an adoption it has not observed.
- Creating an adoption requires `expected_section_version` matching the target course section's current `version`. Because creation legitimately supersedes a prior approved adoption for the same section and title, the client's view of which adoption is in force must be current.
- Committing a buy plan requires `expected_buy_plan_version` matching the plan's current `version`. The tier projection and budget arithmetic the client relied on were computed from the plan's quantities; a stale read invalidates that arithmetic.
- Creating a buyback ticket requires `expected_title_version` matching the title's current `version`. Needs-based versus wholesale variant selection depends on demand-quota consumption and stock movements, both of which advance the title's `version`.

### 2.8. Validation Precedence

When multiple checks could reject the same request, they are evaluated in a fixed priority order, and the first failing check determines the error returned. Required-field presence and request-body shape failures (`ERR_VALIDATION`) are raised as the body is parsed and may surface before the layered checks below; the numbered ordering governs the layered checks themselves:

1. Authentication: `X-User-Role` and `X-User-ID` present and the role declared (`ERR_UNAUTHENTICATED`).
2. Authorization: the role is permitted on the endpoint (`ERR_FORBIDDEN`).
3. Existence: path identifiers and body foreign-key identifiers must exist, validated left to right as they appear in the URL and payload (`ERR_NOT_FOUND`).
4. Ownership on owner-scoped endpoints: a `Faculty` actor matches the adoption's `faculty_id`; a `Student` actor matches the order, charge, or ticket `student_id` (`ERR_NOT_OWNER`). Because ownership is a property of a loaded resource, a missing path identifier yields `ERR_NOT_FOUND` before any ownership comparison.
5. State: the target resource is in a valid from-state for the requested transition (`ERR_INVALID_STATE`), including the specific case of opt-out or revoke attempted on an already-billed inclusive-access charge (`ERR_CHARGE_ALREADY_BILLED`), and the optimistic-concurrency check (`ERR_STALE_VERSION`) — all three evaluated after existence and before any business rule.
6. Business safety: the price-posting requirement at adoption submit (`ERR_PRICE_POSTING_REQUIRED`) and the segregation-of-duties separation at commission issue (`ERR_SOD_COMMISSION_CONFLICT`).
7. Business temporal: the census instant reached (`ERR_CENSUS_NOT_REACHED`); the aid window open for fully aid-tendered orders (`ERR_AID_WINDOW_CLOSED`); the add/drop return deadline (`ERR_RETURN_WINDOW_CLOSED`); the 48-hour digital return limit (`ERR_DIGITAL_NOT_RETURNABLE`); the inclusive-access opt-out deadline (`ERR_OPT_OUT_WINDOW_CLOSED`); the ticket quote validity (`ERR_QUOTE_EXPIRED`); and the buyback window (`ERR_BUYBACK_WINDOW_CLOSED`).
8. Business constraint: field shape and bounds (`ERR_VALIDATION`) — including a request body that is not a JSON object, while a missing or empty body is treated as an empty object so that required-field validation fires uniformly; format offered by the title (`ERR_FORMAT_NOT_OFFERED`); duplicate non-terminal adoption for a section and title (`ERR_DUPLICATE_ADOPTION`); duplicate enrollment (`ERR_ENROLLMENT_DUPLICATE`); section capacity (`ERR_SECTION_CAPACITY_REACHED`); stock sufficiency (`ERR_INSUFFICIENT_STOCK`); agreement overlap (`ERR_AGREEMENT_OVERLAP`); wholesale quote window overlap (`ERR_QUOTE_WINDOW_OVERLAP`); duplicate non-terminal commission statement (`ERR_DUPLICATE_COMMISSION_STATEMENT`).
9. Business referential: an active publisher agreement covers the title's publisher at now (`ERR_NO_ACTIVE_AGREEMENT`); the referenced adoption is approved (`ERR_ADOPTION_NOT_APPROVED`); the wholesale variant has an active quote (`ERR_WHOLESALE_QUOTE_MISSING`); the term's compliance posture permits commission issue (`ERR_TERM_NOT_COMPLIANT`).
10. Business fiscal: the term buy budget (`ERR_TERM_BUDGET_EXCEEDED`) and full aid coverage of an aid-only order (`ERR_INSUFFICIENT_AID`).

### 2.9. Calendar Windows and Boundary Semantics

The academic term carries the full calendar: `registration_open_at`, `price_posting_deadline_at`, `adoption_deadline_at`, `aid_charge_window_start_at`, `aid_charge_window_end_at`, `add_drop_return_deadline_at`, `census_at`, `ia_opt_out_deadline_at`, `buyback_window_start_at`, and `buyback_window_end_at`. All of these instants are **inclusive** boundaries: an adoption whose `submitted_at` is exactly equal to `adoption_deadline_at` is on time; the aid charge window contains both its start and its end; a return at exactly `add_drop_return_deadline_at` is within window; an opt-out at exactly `ia_opt_out_deadline_at` is allowed; and the buyback window contains both endpoints. Census billing runs at or after `census_at`. Publisher agreements, by contrast, use calendar dates: `start_date` and `end_date` are `YYYY-MM-DD` strings forming a **closed** interval, so an agreement covers a title's publisher from the start date through the end date inclusive. Wholesale quotes use **half-open** windows: `effective_from` is inclusive and `effective_to` is exclusive, so a quote whose `effective_from` equals a prior quote's `effective_to` sits adjacent without overlapping.

### 2.10. Cascading Mutations and Aggregate Consistency

Several operations in this domain mutate more than one entity in a single atomic action, and each hop of each cascade increments the affected entity's `version` and refreshes its `updated_at`. Three named cascades recur throughout §3. **CASCADE-1** runs when adoption closes for a term: un-submitted adoptions expire (hop 1), each expiry recomputes its section's compliance standing (hop 2), and each compliance flip recomputes the term's non-compliant section count and posture (hop 3). **CASCADE-2** runs when an order line is returned: the line mutation recomputes the parent order's `refund_total_cents` and re-derives the order's status. The inclusive-access cascade runs at section lock, at census billing, and at enrollment drop, creating, billing, cancelling, or refunding charges as the surrounding workflow dictates. Nested retrieval follows the same left-to-right discipline as §2.8 priority 3: for a nested path such as an order's line, the order is resolved first and the line second, and the first missing identifier yields `ERR_NOT_FOUND`.

## 3. Business Logic & Workflows

### 3.1. The Academic Term and Its Lifecycle

Everything hangs off the academic term. A `PlatformAdmin` creates a term by supplying its unique `code` (for example "2026-FALL"; a duplicate `code` is rejected with `ERR_VALIDATION`), its `length_weeks` (a positive integer that later drives the rental pricing tier), the full calendar of §2.9, and `buy_budget_cents`, the term-level cap on committed buy-plan landed cost, which must be at least 0. A new term begins in `SETUP`, with `noncompliant_section_count` at 0 and `compliance_posture` at `CLEAR`.

From `SETUP`, a `PlatformAdmin` opens adoption, moving the term to `ADOPTION_OPEN`. From `ADOPTION_OPEN`, a `BookstoreManager` closes adoption, moving the term to `ADOPTION_CLOSED` and firing CASCADE-1: every adoption of a section in this term still sitting in `DRAFT` or `RETURNED` is swept to `EXPIRED`; each expiring adoption recomputes its section's `compliance_status`, which becomes `NON_COMPLIANT` if the section has zero approved adoptions or has any adoption — in any status — whose `late_flag` is true, and otherwise becomes `COMPLIANT`; a section with no expiring adoption is not recomputed by this cascade at all and keeps whatever `compliance_status` it already had — adoption close is the only step that ever recomputes section compliance, so a section whose adoptions are all `APPROVED` going into the sweep remains `PENDING` rather than turning `COMPLIANT`; and each section flip recomputes the term's `noncompliant_section_count` (the count of `NON_COMPLIANT` sections in the term) and its `compliance_posture`, which becomes `RESTRICTED` when that count is greater than 0 and `CLEAR` otherwise. The term's `version` increments at each lifecycle step.

From `ADOPTION_CLOSED`, a `BookstoreManager` opens sales (`SALES_OPEN`). From `SALES_OPEN`, the manager runs census billing, but only once now has reached the term's `census_at`; an earlier attempt is rejected with `ERR_CENSUS_NOT_REACHED`. Census billing transitions every inclusive-access charge in `PENDING` whose section is `LOCKED` to `BILLED`, applying the billing split of §3.7, and the term lands in `CENSUS_DONE`. From `CENSUS_DONE`, the manager opens buyback (`BUYBACK_OPEN`). Finally, from `BUYBACK_OPEN`, the manager closes the term: every buyback ticket still `QUOTED` whose `quote_valid_until` is at or before now moves to `EXPIRED`, every order of the term in `SETTLED` or `PARTIALLY_REFUNDED` moves to `CLOSED`, every section of the term in `LOCKED` moves to `CLOSED`, and the term itself reaches the terminal `TERM_CLOSED`.

### 3.2. Publishers, Agreements, Titles, and Wholesale Quotes

A `PlatformAdmin` registers each publisher by its unique `name` (a duplicate name is rejected with `ERR_VALIDATION`), and then negotiates deals against it. Creating an agreement for a publisher takes a `start_date` and `end_date` forming a closed interval — a `start_date` after `end_date` is rejected with `ERR_VALIDATION` — a `discount_pct` for new print, a `digital_discount_pct` for digital format, and a `commission_pct` paid to the institution on net sales — each percentage at least 0 and strictly less than 1. Two agreements for the same publisher may not overlap on their closed intervals: an overlap exists when the new agreement's `start_date` is on or before the existing agreement's `end_date` and the new `end_date` is on or after the existing `start_date`. Note that adjacency counts as overlap here — a new agreement starting exactly on the day an existing one ends is rejected with `ERR_AGREEMENT_OVERLAP`. An agreement "covers" a publisher at a given instant when the current date falls inside its closed interval; approval of an adoption, commitment of a buy plan, and placement of an order all require such an active agreement for the title's publisher, failing with `ERR_NO_ACTIVE_AGREEMENT` otherwise.

Titles are the tradable unit. Creating a title takes a unique `isbn` (ISBN-13), stored as an opaque string with uniqueness as the only enforced constraint — a duplicate `isbn` is rejected with `ERR_VALIDATION` — the `publisher_id` it belongs to, a strictly positive `list_price_cents`, four format flags — `has_new`, `has_used`, `has_rental`, `has_digital` — and optional seeded stock `initial_new_stock_qty`, `initial_used_stock_qty`, and `initial_rental_stock_qty`, each defaulting to 0. The seeded values initialize the computed on-hand counters `new_stock_qty`, `used_stock_qty`, and `rental_stock_qty`, which then move with every placement, return, receipt, and buyback in the domain.

Wholesale quotes express the outside market for a used copy. A `PlatformAdmin` posts a quote against a title with a `condition` grade of `LIKE_NEW`, `GOOD`, or `ACCEPTABLE`, a strictly positive `price_cents`, and a half-open `effective_from` / `effective_to` window in which `effective_from` must be strictly before `effective_to` (otherwise `ERR_VALIDATION`). Two quotes for the same title and condition may not overlap on half-open semantics — overlap exists when the new `effective_from` is before the existing `effective_to` and the new `effective_to` is after the existing `effective_from` — and unlike agreements, adjacency is permitted: a quote whose `effective_from` equals a prior quote's `effective_to` does not overlap and is accepted. A violating quote is rejected with `ERR_QUOTE_WINDOW_OVERLAP`.

### 3.3. Sections, Enrollments, and the Rosters Behind Billing

Before sections can exist, a `PlatformAdmin` registers the people: each faculty record carries a `full_name` and a unique `email`, and each student record carries a `full_name`, a unique `email`, and an optional `awarded_aid_cents` — the total financial aid awarded for charges, defaulting to 0 and required to be at least 0 — which seeds the student's computed `aid_balance_cents` at creation; a duplicate `email` (within the same record type) is rejected with `ERR_VALIDATION`. After creation, a `FinanceAdmin` may adjust a student's aid by supplying a signed `delta_cents` together with a `reason`; both `awarded_aid_cents` and `aid_balance_cents` move by that delta, and the student's `version` increments. The adjustment responds with HTTP 201 carrying the updated student record.

A `PlatformAdmin` creates a course section inside a term by supplying the `term_id`, the `faculty_id` of the instructor of record (this is the adoption ownership anchor), a `course_code` such as CS101, a `section_code` unique within the combination of term and course (a duplicate is rejected with `ERR_VALIDATION`), an `enrollment_capacity` of at least 0, and the inclusive-access configuration: `ia_enabled`, and `ia_material_fee_cents`, which is required exactly when `ia_enabled` is true and must be at least 0; if supplied while `ia_enabled` is false, it is still validated to be at least 0 and stored. A new section is `DRAFT` with `compliance_status` `PENDING`.

A `PlatformAdmin` opens a section, moving it from `DRAFT` to `OPEN`, but only while its term is in `ADOPTION_OPEN`, `ADOPTION_CLOSED`, or `SALES_OPEN`. Enrollments are created against a section by `PlatformAdmin`, one per student: supplying a `student_id` yields an `ENROLLED` enrollment, provided no enrollment already exists for the same section and student (`ERR_ENROLLMENT_DUPLICATE`) and the count of `ENROLLED` enrollments is still below the section's `enrollment_capacity` (`ERR_SECTION_CAPACITY_REACHED`).

When sales are open and the roster is settled, a `BookstoreManager` locks the section, moving it from `OPEN` to `LOCKED` — permitted only while the term is `SALES_OPEN`. If the section has `ia_enabled`, locking generates one inclusive-access charge per `ENROLLED` enrollment: each charge is created in `PENDING`, tied to its `enrollment_id` (at most one charge per enrollment), stamped with the section, student, and term, with its `fee_cents` locked from the section's `ia_material_fee_cents` at that moment, and with `aid_applied_cents` and `balance_due_cents` initialized to 0 and `opted_out_at` unset. Later edits to the section fee do not propagate.

Dropping an enrollment moves it from `ENROLLED` to `DROPPED`. A student may drop their own enrollment — the enrollment's `student_id` must equal `X-User-ID`, otherwise `ERR_NOT_OWNER` — but only while the section is not `LOCKED`; a student drop against a locked section fails with `ERR_INVALID_STATE`. A `BookstoreManager` may drop any enrollment. Dropping cascades into inclusive access as described in §3.7. Sections themselves reach terminal `CLOSED` only through the term-close cascade of §3.1.

### 3.4. Faculty Adoptions and the Price-Transparency Loop

An adoption is a faculty member's declaration that a section will use a title, in declared quantities per format. A `Faculty` actor creates an adoption by naming the `section_id` and `title_id`, the requested quantities `qty_new_requested`, `qty_used_requested`, `qty_rental_requested`, and `qty_digital_requested` (each at least 0), optionally the `posted_price_cents` (which, when present, must be at least 0), and the `expected_section_version` required by §2.7. Creation is owner-scoped through the section: the acting faculty's `X-User-ID` must equal the section's `faculty_id` — the value copied onto the new adoption — failing with `ERR_NOT_OWNER` otherwise (checked after section and title existence, per §2.8). The adopted formats must actually be offered by the title — a requested new quantity on a title without `has_new`, and likewise for `has_used`, `has_rental`, and `has_digital`, is rejected with `ERR_FORMAT_NOT_OFFERED`. At most one non-terminal adoption may exist for a given section and title: an existing adoption in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`, or `RETURNED` for the same pair blocks creation with `ERR_DUPLICATE_ADOPTION`. The new adoption's `faculty_id` is copied from the section, and its `status` begins at `DRAFT` with `submitted_at` unset, `late_flag` and `transparency_late_flag` false, and no `review_note`.

Creation has a supersede side effect: if an `APPROVED` adoption exists for the same section and title, the incoming adoption replaces it — the prior adoption moves from `APPROVED` to `SUPERSEDED`, and the prior adoption's buy plan, if still `DRAFT`, moves to `CANCELLED`. Creation also bumps the section's `version` by one, which is precisely why §2.7 requires the caller to pin `expected_section_version`.

While `DRAFT`, the owning faculty member may edit the quantities and `posted_price_cents` through the adoption edit operation, which requires `expected_adoption_version` per §2.7. The edit is partial: quantity fields that are omitted or null are left unchanged, while an explicit null `posted_price_cents` clears the posted price. Submission is the HEOA compliance moment: the faculty owner submits the adoption, moving it from `DRAFT` to `SUBMITTED`. Submission requires the adoption's `faculty_id` to equal `X-User-ID` (`ERR_NOT_OWNER` otherwise), requires the term to be in `ADOPTION_OPEN` (`ERR_INVALID_STATE` otherwise), and — the price-transparency mandate — requires `posted_price_cents` to be set; a submit with a null posted price is rejected with `ERR_PRICE_POSTING_REQUIRED`. A successful submit stamps `submitted_at` with now, sets `late_flag` to true exactly when now is after the term's `adoption_deadline_at`, and sets `transparency_late_flag` to true exactly when now is after the term's `price_posting_deadline_at`. These flags are permanent evidence for the compliance computation at adoption close.

Review is the manager's domain. A `BookstoreManager` starts review, moving `SUBMITTED` to `UNDER_REVIEW`. From `UNDER_REVIEW` there are two exits. Approval moves the adoption to `APPROVED`, but only when an active publisher agreement covers the title's publisher at now — otherwise `ERR_NO_ACTIVE_AGREEMENT` — and approval creates a buy plan in `DRAFT` whose `adoption_id` points back and whose decided quantities `qty_new`, `qty_used`, `qty_rental`, and `qty_digital` are initialized from the adoption's requested quantities; the plan's computed fields start empty (`landed_cost_cents` and `discount_pct_applied` at 0, `tier_bonus_applied` false, `committed_by_user_id` unset) until commit populates them. Return moves the adoption to `RETURNED` and stores the manager's `review_note`, which is a required string on that operation. A returned adoption is not dead: the owning faculty member can revise it through the same edit operation, which — when the adoption is `RETURNED` and the term is back in `ADOPTION_OPEN` — moves it back to `DRAFT`, clears the `review_note`, clears `submitted_at`, resets both late flags to false, and increments the adoption's `version`. The adoption's terminal states are `EXPIRED` (reached via the adoption-close sweep from `DRAFT` or `RETURNED`) and `SUPERSEDED`.

### 3.5. Buy Plans: Tiered Landed Cost, Budget, and Receipt

Every approved adoption spawns exactly one buy plan — `adoption_id` is unique across plans — and while the plan is `DRAFT`, a `BookstoreManager` may adjust the decided quantities `qty_new`, `qty_used`, `qty_rental`, and `qty_digital` away from the adoption's request, each at least 0.

Commitment is the fiscal heart of the purchasing workflow. A `BookstoreManager` commits a `DRAFT` plan, which requires the source adoption to be `APPROVED` (`ERR_ADOPTION_NOT_APPROVED` otherwise), requires an active agreement covering the title's publisher at now (`ERR_NO_ACTIVE_AGREEMENT`), and requires `expected_buy_plan_version` per §2.7 (`ERR_STALE_VERSION` on mismatch). The landed-cost computation then runs in a pinned evaluation order. First, gross units are the sum of the plan's `qty_new`, `qty_used`, `qty_rental`, and `qty_digital`. Second, projected units add to gross units the same four-quantity sum over every other buy plan in `COMMITTED` or `RECEIVED` in the same term whose adoption's title shares this plan's publisher. Third, a tier bonus of 0.02 applies when projected units are at least 100; otherwise the bonus is 0. Fourth, `discount_pct_applied` is the active agreement's `discount_pct` plus the tier bonus. Fifth, the unit new cost is the title's `list_price_cents` multiplied by one minus `discount_pct_applied`, rounded half-up to integer cents. Sixth, `landed_cost_cents` is `qty_new` multiplied by that unit new cost. The flag `tier_bonus_applied` records whether the bonus was granted. Note the deliberate asymmetry: the tier is selected on projected volume including this plan, but the bonus applies only to this plan's cost — there is no retroactive repricing of earlier plans.

Commitment also enforces the term budget: the sum of `landed_cost_cents` over all `COMMITTED` and `RECEIVED` plans in the term, plus this plan's `landed_cost_cents`, must not exceed the term's `buy_budget_cents`; a commit that would breach the cap is rejected with `ERR_TERM_BUDGET_EXCEEDED`. A successful commit stamps `committed_by_user_id` with the acting manager's `X-User-ID` — this is the segregation-of-duties anchor revisited in §3.9 — and moves the plan to `COMMITTED`.

Receipt turns paper into stock. A manager receives a `COMMITTED` plan by supplying `received_new_qty`, `received_used_qty`, and `received_rental_qty`; each received quantity must not exceed the corresponding committed quantity, or the request fails with `ERR_VALIDATION`. Receipt adds the received amounts to the title's `new_stock_qty`, `used_stock_qty`, and `rental_stock_qty` respectively, increments both the title's and the plan's `version`, and moves the plan to the terminal `RECEIVED`. A plan may instead be cancelled from `DRAFT` or `COMMITTED`, landing in terminal `CANCELLED`; cancellation from `DRAFT` also happens automatically through the supersede cascade of §3.4.

### 3.6. Orders: Shelf Pricing and the Aid Tender Waterfall

A student places an order by naming the `term_id`, an optional `aid_only` flag defaulting to false, and `lines`, a non-empty array of line requests (an absent, non-array, or empty `lines` is `ERR_VALIDATION`) each carrying an `adoption_id`, a `format` of `NEW`, `USED`, `RENTAL`, or `DIGITAL`, and a `qty` of at least 1 — with the special rule that `qty` must be exactly 1 for `RENTAL` and `DIGITAL` lines. The order's `student_id` is taken from `X-User-ID`. Each referenced adoption must be `APPROVED` (`ERR_ADOPTION_NOT_APPROVED`), an active agreement must cover each title's publisher at now (`ERR_NO_ACTIVE_AGREEMENT`), the requested format must be offered by the title (`ERR_FORMAT_NOT_OFFERED`), and the title's on-hand stock for the requested format must cover the request (`ERR_INSUFFICIENT_STOCK`) — stock sufficiency is evaluated per (title, format) pair against the summed quantity across all lines of the request, so two lines for the same title and format are checked against their combined quantity.

Shelf pricing resolves each line's `unit_price_cents` at placement. For `NEW`, the base is the title's `list_price_cents`. For `USED`, the base is 75% of the list price, rounded half-up to integer cents. For `RENTAL`, the base is a percentage of list that depends on the term's `length_weeks`: 40% when the term runs at most 8 weeks, 50% when it runs 9 to 16 weeks, and 60% when it runs 17 weeks or more — the chosen product rounded half-up to integer cents. For `DIGITAL`, the base is the list price reduced by the active agreement's `digital_discount_pct`, rounded half-up to integer cents. The HEOA price cap then applies: `unit_price_cents` is the smaller of the format base and the adoption's `posted_price_cents`, so the posted transparency price is a hard upper bound on what a student can be charged. The line's `line_total_cents` is the unit price times `qty`, and the order's `total_cents` is the sum of its line totals. Placement decrements stock: a `NEW` line reduces `new_stock_qty`, a `USED` line reduces `used_stock_qty`, a `RENTAL` line reduces `rental_stock_qty`, and `DIGITAL` touches no stock counter.

Tendering then runs as a waterfall over the new order's lines in request-array order. The aid window is open when now falls between `aid_charge_window_start_at` and `aid_charge_window_end_at` inclusive. If `aid_only` is true and the window is not open, the whole placement fails with `ERR_AID_WINDOW_CLOSED`. The remaining aid starts at the student's `aid_balance_cents` when the window is open and at 0 when it is closed. Walking the lines in array order, each line's `aid_tendered_cents` is the smaller of its `line_total_cents` and the remaining aid; its `card_tendered_cents` is the remainder of the line total; and the remaining aid decreases by the aid just applied. The order's `aid_tendered_cents` and `card_tendered_cents` are the per-line sums. If `aid_only` is true and the summed aid falls short of `total_cents`, the placement fails with `ERR_INSUFFICIENT_AID` (HTTP 402). Otherwise the student's `aid_balance_cents` is debited by the order's `aid_tendered_cents`. Each created line is stamped with its parent `order_id` and a `title_id` copied from the referenced adoption, so the line permanently pins the title, section, and posted price context of the purchase. An order is born directly in `SETTLED` — there is no pending state — and each of its lines is born `FULFILLED`.

Reading an order is owner-scoped for the `Student` role in the sense of §2.1: fetching a single order, and listing a single order's lines, both require the order's `student_id` to equal `X-User-ID`, failing with `ERR_NOT_OWNER` otherwise. The store-wide order list endpoint is not owner-scoped and applies no ownership filter.

### 3.7. Returns, Refunds, and Restocking

Either the owning student or a `BookstoreManager` may return a `FULFILLED` line of an order in `SETTLED` or `PARTIALLY_REFUNDED`. A student returning a line must own the order — its `student_id` must equal `X-User-ID`, otherwise `ERR_NOT_OWNER`. The deadline depends on format. A `DIGITAL` line is returnable only within 48 hours of the order's `created_at`, the boundary being inclusive — a return at exactly 48 hours after placement is still allowed; beyond that, the return is rejected with `ERR_DIGITAL_NOT_RETURNABLE`. Any other format is returnable through the term's `add_drop_return_deadline_at` inclusive; past that instant the return is rejected with `ERR_RETURN_WINDOW_CLOSED` — unless the actor is a `BookstoreManager` supplying `override` as true (a boolean defaulting to false when omitted), in which case the return proceeds under the manager-override variant.

Refund size has two variants. Within the applicable window, the refund is the full `line_total_cents`, returned to the original tenders. Under manager override past the add/drop deadline, the refund is 80% of the line total rounded half-up to integer cents — the store keeps a 20% restocking share, which counts as net revenue. Either way, the split between tenders mirrors the original waterfall: `aid_refunded_cents` is the smaller of the line's `aid_tendered_cents` and the refund amount, and `card_refunded_cents` is the remainder of the refund. The student's `aid_balance_cents` is credited by `aid_refunded_cents`, bumping the student's `version`; a zero aid refund is a no-op that leaves the student record untouched.

Restocking mirrors placement: a returned `NEW` line adds `qty` back to the title's `new_stock_qty`, `USED` to `used_stock_qty`, `RENTAL` to `rental_stock_qty`, and `DIGITAL` restocks nothing. CASCADE-2 then recomputes the parent order: `refund_total_cents` becomes the sum of all line refunds, and the order's status is re-derived — the first return against a `SETTLED` order moves it to `PARTIALLY_REFUNDED`, the order stays `PARTIALLY_REFUNDED` while more lines remain open, and when the last open line is returned the order reaches terminal `REFUNDED`. Orders in `SETTLED` or `PARTIALLY_REFUNDED` that survive to term close are swept to `CLOSED` by the cascade of §3.1.

### 3.8. Inclusive Access: Opt-Out, Census Billing, and Refund

Inclusive-access charges are created at section lock (§3.3) and cycle through `PENDING`, `OPTED_OUT`, `BILLED`, `REFUNDED`, and `CANCELLED`. While a charge is `PENDING`, the owning student may opt out — the charge's `student_id` must equal `X-User-ID`, otherwise `ERR_NOT_OWNER` — provided now is on or before the term's `ia_opt_out_deadline_at`; a late opt-out is rejected with `ERR_OPT_OUT_WINDOW_CLOSED`. Opting out stamps `opted_out_at` and moves the charge to `OPTED_OUT`. A student who changes their mind may revoke the opt-out before the same deadline, clearing `opted_out_at` and returning the charge to `PENDING`. Either action attempted on a charge already `BILLED` is rejected with `ERR_CHARGE_ALREADY_BILLED`.

Census billing, fired from the term lifecycle of §3.1 once `census_at` has been reached, bills every `PENDING` charge in a `LOCKED` section. For each charge, the aid split is computed: when now falls inside the aid charge window (both boundaries inclusive), `aid_applied_cents` is the smaller of the charge's `fee_cents` and the student's current `aid_balance_cents`; outside the window it is 0. The `balance_due_cents` is the fee minus the aid applied. The student's `aid_balance_cents` is debited by the aid applied, incrementing the student's `version`, and the charge moves to `BILLED`.

Two paths unwind a charge. A `BookstoreManager` may refund a `BILLED` charge directly: the student's `aid_balance_cents` is credited back by `aid_applied_cents`, then both `aid_applied_cents` and `balance_due_cents` are zeroed and the charge lands in terminal `REFUNDED`. The same `REFUNDED` outcome — with the same aid credit and zeroing — happens automatically when the underlying enrollment is dropped after billing. Dropping an enrollment whose charge is still `PENDING` or `OPTED_OUT` instead moves the charge to terminal `CANCELLED`.

### 3.9. Buyback: Dual-Variant Offers and the Ticket Lifecycle

At end of term the store buys used copies back, pricing each offer by one of two variants. A student requests a buyback quote by supplying the `title_id`, a declared `condition` of `LIKE_NEW`, `GOOD`, or `ACCEPTABLE`, the `upcoming_term_id` whose adoptions define demand, and `expected_title_version` per §2.7; the ticket's `student_id` comes from `X-User-ID`. Creation — like acceptance — requires an open buyback window: some term must be in `BUYBACK_OPEN` with now between its `buyback_window_start_at` and `buyback_window_end_at` inclusive, otherwise the request fails with `ERR_BUYBACK_WINDOW_CLOSED`.

Variant selection is demand-driven. The demand quota for a title and upcoming term is the sum of `qty_used_requested` over the `APPROVED` adoptions of that title in that term, and the consumed count is the number of tickets for the same pair already in `ACCEPTED` or `PAID`. When the quota is positive and not yet fully consumed, the ticket's `pricing_variant` is `NEEDS_BASED` and its `quoted_price_cents` is 50% of the title's `list_price_cents` rounded half-up — a flat half of new list regardless of condition. Otherwise the variant is `WHOLESALE` and the quoted price is the `price_cents` of the unique wholesale quote for the title and declared condition whose half-open window contains now; if no such quote exists, creation fails with `ERR_WHOLESALE_QUOTE_MISSING`. Either way, `quote_valid_until` is stamped at now plus 24 hours, and the ticket begins at `QUOTED`. Ticket creation itself increments the title's `version` — alongside the demand-quota consumption and stock movements of §2.7 — which is why creation pins `expected_title_version`.

The student accepts a `QUOTED` ticket — ownership-checked via `student_id` (`ERR_NOT_OWNER`) — no later than `quote_valid_until` (the validity boundary is inclusive, so acceptance at exactly `quote_valid_until` succeeds), else `ERR_QUOTE_EXPIRED`, and within an open buyback window as above. Acceptance consumes one unit of the demand quota (the accepted/paid count increments), adds one to the title's `used_stock_qty` with a title `version` bump, and moves the ticket to `ACCEPTED`. A `BookstoreManager` then pays an `ACCEPTED` ticket, moving it to terminal `PAID`. Alternatively, a manager rejects a ticket: from `QUOTED` this simply lands in terminal `REJECTED` with an optional `reason` (accepted but not persisted on the ticket), but from `ACCEPTED` — the intake condition-mismatch case — rejection compensates: the title's `used_stock_qty` is decremented by one, the demand quota consumption is released, and the ticket lands in `REJECTED`. Tickets still `QUOTED` whose validity has passed are swept to `EXPIRED` at term close.

### 3.10. Commission Statements and Segregation of Duties

The institution earns a commission on net sales, settled per publisher per term. A `FinanceAdmin` creates a statement by naming the `publisher_id` and `term_id`; at most one non-terminal statement — one in `DRAFT` or `ISSUED` — may exist for a publisher and term, with duplicates rejected as `ERR_DUPLICATE_COMMISSION_STATEMENT`. Creation computes a `PROVISIONAL` snapshot, recorded in `calculation_variant`.

The commission math aggregates per title and rounds per title before summing — never sum-then-round. For each title of the statement's publisher, title gross is the sum of `line_total_cents` over all order lines of that title in orders of the statement's term, counting both `FULFILLED` and `RETURNED` lines. Title returns are the sum of `aid_refunded_cents` plus `card_refunded_cents` over those same lines, counting only refunds processed before the calculation time. Title net is gross minus returns, and the title's commission is the net multiplied by the active agreement's `commission_pct`, rounded half-up to integer cents; if no active agreement covers the publisher at calculation time, the commission percentage is treated as 0 rather than failing. The statement's `gross_sales_cents`, `returns_cents`, and `net_sales_cents` are the per-title sums (net being gross minus returns), and `commission_cents` is the sum of the per-title rounded commissions.

Issuing moves the statement from `DRAFT` to `ISSUED` and carries two gates, evaluated in §2.8 precedence order (safety before referential), so when both fail the SoD error is the one returned. First, segregation of duties: the issuing `FinanceAdmin`'s `X-User-ID` must differ from the `committed_by_user_id` of every buy plan in `COMMITTED` or `RECEIVED` for this publisher in this term; a match means the same operator committed purchasing and is now certifying the commission on it, and the issue is rejected with `ERR_SOD_COMMISSION_CONFLICT` (HTTP 403). Second, the term's `compliance_posture` must be `CLEAR`; issuing into a `RESTRICTED` term — one with non-compliant sections at adoption close — is rejected with `ERR_TERM_NOT_COMPLIANT`. A successful issue recomputes the commission with the `FINAL` variant — folding in all returns processed between creation and issue — locks the numbers, stamps `issued_by_user_id`, and increments the statement's `version`. Settlement finally moves an `ISSUED` statement to terminal `SETTLED`.

## 4. Endpoint Definitions

All endpoints are mounted under `/bookstore`. Creating a new resource returns HTTP 201 — as does the aid-adjustment endpoint, which responds 201 with the updated student — while other state transitions, modifications, and reads return HTTP 200. Request bodies, computed fields, side effects, and rejection conditions are specified in §2 and §3; this table is a routing summary only. List endpoints accept `limit` and `offset` and default to `created_at` ascending order; the supported filters are: terms by `status`; titles by `publisher_id`; a title's wholesale quotes by `condition`; sections by `term_id`, `faculty_id`, and `status`; enrollments by `section_id`, `student_id`, and `status`; adoptions by `section_id`, `title_id`, `faculty_id`, and `status`; orders by `student_id`, `term_id`, and `status`; cross-order order lines by `order_id`, `adoption_id`, and `title_id`; inclusive-access charges by `student_id`, `section_id`, `enrollment_id`, `term_id`, and `status`; buyback tickets by `student_id`, `title_id`, `upcoming_term_id`, and `status`; and commission statements by `publisher_id`, `term_id`, and `status`.

| Method | Path | Description | Authorized Role(s) |
|---|---|---|---|
| POST | /bookstore/_clock/set_current_utc | Set the logical clock to a supplied instant | PlatformAdmin |
| POST | /bookstore/terms | Create an academic term in SETUP | PlatformAdmin |
| GET | /bookstore/terms | List terms | PlatformAdmin, BookstoreManager, FinanceAdmin, Faculty, Student |
| GET | /bookstore/terms/{id} | Get a term | PlatformAdmin, BookstoreManager, FinanceAdmin, Faculty, Student |
| POST | /bookstore/terms/{id}/open-adoption | SETUP to ADOPTION_OPEN | PlatformAdmin |
| POST | /bookstore/terms/{id}/close-adoption | ADOPTION_OPEN to ADOPTION_CLOSED with CASCADE-1 | BookstoreManager |
| POST | /bookstore/terms/{id}/open-sales | ADOPTION_CLOSED to SALES_OPEN | BookstoreManager |
| POST | /bookstore/terms/{id}/run-census-billing | SALES_OPEN to CENSUS_DONE; bills PENDING IA charges in LOCKED sections | BookstoreManager |
| POST | /bookstore/terms/{id}/open-buyback | CENSUS_DONE to BUYBACK_OPEN | BookstoreManager |
| POST | /bookstore/terms/{id}/close | BUYBACK_OPEN to TERM_CLOSED; expires stale quotes, closes orders and sections | BookstoreManager |
| POST | /bookstore/publishers | Create a publisher | PlatformAdmin |
| GET | /bookstore/publishers | List publishers | PlatformAdmin, BookstoreManager, FinanceAdmin |
| GET | /bookstore/publishers/{id} | Get a publisher | PlatformAdmin, BookstoreManager, FinanceAdmin |
| POST | /bookstore/publishers/{id}/agreements | Create a publisher agreement; closed-interval overlap rejected | PlatformAdmin |
| GET | /bookstore/publishers/{id}/agreements | List a publisher's agreements | PlatformAdmin, BookstoreManager, FinanceAdmin |
| POST | /bookstore/titles | Create a title with optional seeded stock | PlatformAdmin |
| GET | /bookstore/titles | List titles | PlatformAdmin, BookstoreManager, FinanceAdmin, Faculty, Student |
| GET | /bookstore/titles/{id} | Get a title including on-hand stock | PlatformAdmin, BookstoreManager, FinanceAdmin, Faculty, Student |
| POST | /bookstore/titles/{id}/wholesale-quotes | Create a wholesale quote; half-open overlap rejected | PlatformAdmin |
| GET | /bookstore/titles/{id}/wholesale-quotes | List a title's quotes | PlatformAdmin, BookstoreManager, Student |
| POST | /bookstore/faculty | Create a faculty record | PlatformAdmin |
| GET | /bookstore/faculty/{id} | Get a faculty record | PlatformAdmin, BookstoreManager, Faculty |
| POST | /bookstore/students | Create a student with an aid award | PlatformAdmin |
| GET | /bookstore/students/{id} | Get a student | PlatformAdmin, BookstoreManager, FinanceAdmin, Student |
| POST | /bookstore/students/{id}/aid-adjustments | Adjust aid award and balance by a signed delta | FinanceAdmin |
| POST | /bookstore/sections | Create a course section in DRAFT | PlatformAdmin |
| GET | /bookstore/sections | List sections | PlatformAdmin, BookstoreManager, Faculty, Student |
| GET | /bookstore/sections/{id} | Get a section | PlatformAdmin, BookstoreManager, Faculty, Student |
| POST | /bookstore/sections/{id}/open | DRAFT to OPEN | PlatformAdmin |
| POST | /bookstore/sections/{id}/lock | OPEN to LOCKED; generates PENDING IA charges when enabled | BookstoreManager |
| POST | /bookstore/sections/{id}/enrollments | Enroll a student; capacity and duplicate checks | PlatformAdmin |
| GET | /bookstore/enrollments | List enrollments | PlatformAdmin, BookstoreManager, Student |
| GET | /bookstore/enrollments/{id} | Get an enrollment | PlatformAdmin, BookstoreManager, Student |
| POST | /bookstore/enrollments/{id}/drop | Drop an enrollment; cascades IA cancel or refund | Student, BookstoreManager |
| POST | /bookstore/adoptions | Create an adoption in DRAFT; supersedes an APPROVED adoption for the same section and title; OCC on section version | Faculty |
| GET | /bookstore/adoptions | List adoptions | PlatformAdmin, BookstoreManager, Faculty |
| GET | /bookstore/adoptions/{id} | Get an adoption | PlatformAdmin, BookstoreManager, Faculty |
| PATCH | /bookstore/adoptions/{id} | Edit quantities and posted price in DRAFT; RETURNED moves back to DRAFT; OCC | Faculty |
| POST | /bookstore/adoptions/{id}/submit | DRAFT to SUBMITTED; stamps submission time and late flags | Faculty |
| POST | /bookstore/adoptions/{id}/start-review | SUBMITTED to UNDER_REVIEW | BookstoreManager |
| POST | /bookstore/adoptions/{id}/approve | UNDER_REVIEW to APPROVED; creates the buy plan | BookstoreManager |
| POST | /bookstore/adoptions/{id}/return | UNDER_REVIEW to RETURNED with a note | BookstoreManager |
| GET | /bookstore/adoptions/{id}/buy-plan | Get the buy plan for an adoption (array of 0 or 1) | BookstoreManager, Faculty |
| GET | /bookstore/buy-plans/{id} | Get a buy plan | BookstoreManager, FinanceAdmin |
| PATCH | /bookstore/buy-plans/{id} | Edit decided quantities while DRAFT | BookstoreManager |
| POST | /bookstore/buy-plans/{id}/commit | DRAFT to COMMITTED; tiered landed cost, budget check, SoD anchor; OCC | BookstoreManager |
| POST | /bookstore/buy-plans/{id}/receive | COMMITTED to RECEIVED; adds received stock to the title | BookstoreManager |
| POST | /bookstore/buy-plans/{id}/cancel | DRAFT or COMMITTED to CANCELLED | BookstoreManager |
| POST | /bookstore/orders | Place an order with lines; shelf pricing, aid waterfall, stock decrement | Student |
| GET | /bookstore/orders | List orders | BookstoreManager, Student |
| GET | /bookstore/orders/{id} | Get an order | BookstoreManager, Student |
| GET | /bookstore/orders/{id}/lines | List an order's lines | BookstoreManager, Student |
| GET | /bookstore/order-lines | List order lines across orders | BookstoreManager |
| GET | /bookstore/order-lines/{id} | Get an order line | BookstoreManager |
| POST | /bookstore/orders/{id}/lines/{line_id}/return | Return a line; full or 80% override refund; restock and cascades | Student, BookstoreManager |
| GET | /bookstore/inclusive-access-charges | List inclusive-access charges | BookstoreManager, Student |
| GET | /bookstore/inclusive-access-charges/{id} | Get an inclusive-access charge | BookstoreManager, Student |
| POST | /bookstore/inclusive-access-charges/{id}/opt-out | PENDING to OPTED_OUT before the deadline | Student |
| POST | /bookstore/inclusive-access-charges/{id}/revoke-opt-out | OPTED_OUT back to PENDING before the deadline | Student |
| POST | /bookstore/inclusive-access-charges/{id}/refund | BILLED to REFUNDED; aid credited back | BookstoreManager |
| POST | /bookstore/buyback-tickets | Create a buyback quote; dual-variant pricing; OCC on title version | Student |
| GET | /bookstore/buyback-tickets | List buyback tickets | BookstoreManager, Student |
| GET | /bookstore/buyback-tickets/{id} | Get a buyback ticket | BookstoreManager, Student |
| POST | /bookstore/buyback-tickets/{id}/accept | QUOTED to ACCEPTED; consumes demand quota; used stock plus one | Student |
| POST | /bookstore/buyback-tickets/{id}/pay | ACCEPTED to PAID | BookstoreManager |
| POST | /bookstore/buyback-tickets/{id}/reject | QUOTED or ACCEPTED to REJECTED; compensates stock and quota from ACCEPTED | BookstoreManager |
| POST | /bookstore/commission-statements | Create a DRAFT statement with a PROVISIONAL calculation | FinanceAdmin |
| GET | /bookstore/commission-statements | List statements | FinanceAdmin, BookstoreManager |
| GET | /bookstore/commission-statements/{id} | Get a statement | FinanceAdmin |
| POST | /bookstore/commission-statements/{id}/issue | DRAFT to ISSUED; FINAL recompute locked; posture gate and SoD | FinanceAdmin |
| POST | /bookstore/commission-statements/{id}/settle | ISSUED to SETTLED | FinanceAdmin |

## 5. Error Code Catalogue

Trigger conditions for each error are specified in §2 and §3; this catalogue lists identifiers and statuses only.

| Error ID | HTTP Status Code |
|---|---|
| ERR_UNAUTHENTICATED | 401 |
| ERR_FORBIDDEN | 403 |
| ERR_NOT_OWNER | 403 |
| ERR_NOT_FOUND | 404 |
| ERR_INVALID_STATE | 409 |
| ERR_CHARGE_ALREADY_BILLED | 409 |
| ERR_STALE_VERSION | 412 |
| ERR_VALIDATION | 400 |
| ERR_PRICE_POSTING_REQUIRED | 422 |
| ERR_SOD_COMMISSION_CONFLICT | 403 |
| ERR_CENSUS_NOT_REACHED | 422 |
| ERR_AID_WINDOW_CLOSED | 422 |
| ERR_INSUFFICIENT_AID | 402 |
| ERR_RETURN_WINDOW_CLOSED | 422 |
| ERR_DIGITAL_NOT_RETURNABLE | 422 |
| ERR_OPT_OUT_WINDOW_CLOSED | 422 |
| ERR_BUYBACK_WINDOW_CLOSED | 422 |
| ERR_QUOTE_EXPIRED | 422 |
| ERR_FORMAT_NOT_OFFERED | 422 |
| ERR_DUPLICATE_ADOPTION | 409 |
| ERR_ENROLLMENT_DUPLICATE | 409 |
| ERR_SECTION_CAPACITY_REACHED | 409 |
| ERR_INSUFFICIENT_STOCK | 409 |
| ERR_AGREEMENT_OVERLAP | 409 |
| ERR_QUOTE_WINDOW_OVERLAP | 409 |
| ERR_DUPLICATE_COMMISSION_STATEMENT | 409 |
| ERR_NO_ACTIVE_AGREEMENT | 422 |
| ERR_ADOPTION_NOT_APPROVED | 422 |
| ERR_WHOLESALE_QUOTE_MISSING | 422 |
| ERR_TERM_NOT_COMPLIANT | 422 |
| ERR_TERM_BUDGET_EXCEEDED | 422 |
