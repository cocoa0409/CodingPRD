# Worklog — task_1948_vaccine_inventory_vfc_program_management

## Step 1: Create Task Directory — 2026-08-15T02:26:00.000Z

Pre-existing per pipeline invocation: `tasks/task_1948_vaccine_inventory_vfc_program_management/` and `workspace/` verified present; no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-15T02:55:00.000Z

All three files are written and lint is clean.

## Summary

Generated the complete scaffold for **task 1948 — Vaccine Inventory & VFC Program Management** under `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/`.

### Files written
- `SCAFFOLD.yaml` (1933 lines) — `scenario`, `domain_name`, `api_prefix`, `complexity_profile`, `response_envelope`, `entities`, `state_machines`, `concurrency_rules`, `calculations`, `validations`, `endpoints`, `errors`, `roles` (no `scaffold_difficulty_design` / `scaffold_corner_design` keys, per spec)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1476 lines) — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (1862 lines) — single top-level key `scaffold_corner_design`

### Complexity profile
- Primary archetype: **compliance_audit**; secondary: **ledger_reconciliation**
- Layers: cascading_side_effects, derived_field_reconciliation, optimistic_concurrency, rate_threshold_triggers
- Topology: hierarchical; State machine shape: branching; Role model: segregation_of_duties

### Contents (per-section counts)
- **Entities (15)**: ProviderSite, StorageUnit, VaccineProduct, Lot, TemperatureReading (common_fields: false — append-only), TemperatureExcursion, Patient, EligibilityScreening, DoseAdministration, VaccineOrder, OrderLine, AllocationReceipt, BorrowTicket, SiteVisitAudit, ShortDateTransfer
- **State machines (8)**: ProviderSite (ACTIVE/SUSPENDED_ORDERING/TERMINATED), Lot (AVAILABLE/QUARANTINED/DEPLETED/EXPIRED/WASTED_CLOSED), TemperatureExcursion (OPEN/UNDER_REVIEW/RESOLVED_VIABLE/RESOLVED_WASTED), VaccineOrder (DRAFT/SUBMITTED/APPROVED/PARTIALLY_RECEIVED/FULLY_RECEIVED/CANCELLED — fork-join), BorrowTicket (OPEN/PARTIALLY_REPAID/REPAID/VOIDED — with self-loop), SiteVisitAudit (SCHEDULED/IN_PROGRESS/FINDINGS_ISSUED/CLOSED_PASS/CLOSED_FAIL/CANCELLED), ShortDateTransfer (INITIATED/IN_TRANSIT/RECEIVED/CANCELLED), DoseAdministration (PENDING_SUBMISSION/SUBMITTED/REJECTED_BY_REGISTRY — cyclic resubmission)
- **Concurrency rules (2)**: order-approve-stale-site (OCC on ProviderSite.version), payback-stale-ticket (OCC on BorrowTicket.version)
- **Calculations (10)**: vfc_eligibility_determination, accountability_balance_reconciliation (provisional vs final_snapshot variants), private_lending_balance (net vs gross_lending_view variants), excursion_peak_temperature, excursion_duration_minutes, doses_written_off_on_wasted_resolution, payback_quantity_validation, short_date_transfer_successor_lot_quantity, allocation_receipt_running_total, tiered_wastage_rate_reporting
- **Validations (21)** ordered by priority (auth → existence → state/OCC → business_safety → business_referential → business_constraint → business_fiscal → business_temporal)
- **Endpoints (79)**: full CRUD + action endpoints + 13 filtered-list endpoints for FK reverse-reachability + `POST /_clock/set_current_utc` (default 2026-08-01T00:00:00Z)
- **Errors (29)** including ERR_STALE_VERSION (412), ERR_STORAGE_UNIT_QUARANTINED, ERR_STOCK_ELIGIBILITY_MISMATCH, ERR_ACCOUNTABILITY_GAP_UNRESOLVED, ERR_OPEN_EXCURSION_EXISTS, ERR_OPEN_BORROW_TICKET_EXISTS, ERR_SAME_STOCK_BORROW, ERR_PAYBACK_EXCEEDS_BORROWED, etc.
- **Roles (3)**: VaccineManager, StateProgramOfficer, ComplianceAuditor — all `identity: opaque`, with strict segregation (managers operate, officers approve orders, auditors run audits/clock; no overlap on exclusive operations)

### Difficulty design (§1.8) — 18 instances, 2 per rule
- **dual_variant_calc**: audit snapshot provisional-vs-final transfer window; private lending net-vs-gross directional
- **combinatorial_formula**: excursion peak deviation (mode a — multi-input branch); tiered wastage rate (mode b — nested rounding where tier is decided on unrounded value)
- **non_linear_state_machine**: DoseAdministration cyclic resubmission; VaccineOrder fork-join partial-or-full receipt
- **transitive_cascade**: temperature-reading → excursion → lot quarantine → site counter (depth 3); audit close-fail → site suspended → order submit blocked (depth 2)
- **priority_pair_validation_conflict**: state-vs-business_safety (expired lot); business_safety-vs-business_fiscal (quarantined unit + over-receipt)
- **boundary_precision_check**: temperature at exactly max (8.0 in range, 8.1 out); payback exactly remaining vs remaining+1
- **cross_entity_state_dependency**: DoseAdministration → StorageUnit quarantine; BorrowTicket payback → paying Lot availability
- **resource_temporal_overlap**: single active excursion per unit (occupancy); expiration window (closed interval on date)
- **compensating_invariant**: payback conserves paying_lot+lender_lot sum; short-date transfer conserves cross-site lot_number total

### Corner design (§1.9) — 45 instances (44 active + 1 excluded stub) across 9 sections
- entities (6), state_machines (7), calculations (6), validations (10), endpoints (3), errors (6), roles (3), cross_cutting_layers (3), consistency_model (1)

### Lint verdict (verbatim)
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(79 endpoints, 15 entities, 18 difficulty instances, 44 active corner instances, 584 calls scanned, 0 violations.)

### Design notes / corrections applied during lint-driven iteration
- Converted `grounds:` and `captures:` from flow style to block style to keep YAML valid under bracketed tokens like `errors[ERR_X]` and `$.data[0].field`.
- Set `api_prefix: ""` so the lint's collection-segment derivation recognizes flat single-resource GETs (`/lots/{id}`, `/storage-units/{id}`, etc.).
- Added 13 top-level filtered-list GET endpoints (`/lots`, `/dose-administrations`, `/borrow-tickets`, etc.) plus `GET /order-lines/{id}` to satisfy FK reverse-reachability (check f).
- Corrected BorrowTicket payback semantics: physical doses flow `paying_lot → from_lot (lender)`, while `to_lot` carries only the `quantity_borrowed_in` IOU (no double-counting of physical inventory). Updated the compensating-invariant instance to assert the conserved quantity across the paying+lender pair.

## Step 3: Copy Shared Files — 2026-08-15T02:57:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T03:05:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/PRD.md` (342 lines).

**Section list**
- §1 Introduction (2 paragraphs: VFC program context + system scope/role model/logical clock)
- §2 Global Specifications — 2.1 Roles & RBAC (with opaque-identity prose for all three roles), 2.2 API Response Structure (byte-verbatim fixed block, verified), 2.3 Pagination (limit 10/1/100, offset 0, created_at ascending), 2.4 Common Resource Properties & Enum Discipline (incl. TemperatureReading's append-only exception: no `updated_at`/`version`), 2.5 Public/Private Stock Segregation, 2.6 Cold Chain Integrity & Quarantine, 2.7 Accountability Ledger & Private Lending Balance (provisional vs final snapshot semantics), 2.8 OCC (both rules: `expected_provider_site_version` on order approval, `expected_borrow_ticket_version` on payback, `ERR_STALE_VERSION`/412, stale-view framing only), 2.9 Nested Retrieval & Filtered Listings (left-to-right 404; all reverse-reachability filters; path-param identifiers named), 2.10 Logical Clock (boot default 2026-08-01T00:00:00Z, no wall-clock fallback, expiry sweep), 2.11 Precision & Rounding, 2.12 Request Validation Order (global priority ladder)
- §3 Business Logic — 9 subsections by business-process timeline: 3.1 site enrollment/lifecycle, 3.2 storage units & product catalog, 3.3 temperature surveillance & excursion disposition, 3.4 lot registration/expiration, 3.5 ordering & allocation receipts, 3.6 patients/screening/dose administration, 3.7 borrowing & payback, 3.8 short-date transfers, 3.9 site-visit audits
- §4 Endpoint Definitions — 79 rows (4 columns: Method, Path, Description, Authorized Role(s)); exact 1:1 match with scaffold endpoints verified
- §5 Error Code Catalogue — 29 rows, 2 columns; exact 1:1 match with scaffold verified

**Scaffold coverage**: all 15 entities, 8 state machines (every transition's from/to states, preconditions with error IDs, and side-effect cascades), both concurrency rules, all 10 calculations (eligibility age/365.25-floor, accountability reconciliation + provisional/final variants, lending balance + gross view, peak-temperature deviation comparison, duration floor-minutes, write-off summation, payback boundary validation, successor-lot merge-or-create, receipt running totals, tiered wastage 0.05/0.10 with 4-dp half-up reporting and unrounded tier comparisons), all 21 validation rules with priority ordering expressed per-endpoint in prose (dose administration's 7-step order, payback's 7-step order, approve's 4-step order, submit, close-pass, terminate), and all endpoint side effects.

**Coverage decisions**: (1) the paying-lot stock-type-match precondition on record-payback has no error ID in the scaffold, so it is expressed as a plain rejection rule without inventing one; (2) "RED forces close-fail" from the calculation comment is expressed as the tier compelling the failure closure path; (3) uniqueness constraints (`vfc_pin`, `ndc_code`, `lot_number` per product+stock-type) are stated as constraints without error IDs, since the scaffold assigns none; (4) path-template variables are covered via an explicit §2.9 sentence naming `{orderId}`, `{excursionId}`, `{ticketId}`, `{transferId}`, `{auditId}`, `{doseId}` in backticks. The two difficulty-design files were not opened or consulted.

**Hard contract reports**
- Contract 1 (field names): 101 required (entities + endpoint inputs + query/path params + common fields), 0 missing — PASS
- Contract 2 (rules): all validation priorities, both OCC rules (endpoint + field + `ERR_STALE_VERSION`/412 named), 100% of transitions/calculations/validation conditions/side effects expressed; sibling branches symmetric — PASS
- Contract 3 (§3 path purity): 434 backticked tokens scanned, 0 starting with `/`, 0 bare HTTP methods, 0 method+path combos — PASS
- §2.2 verbatim: byte-identical match confirmed; no pseudocode operators or fuzzy approximators found in prose.

## Step 6: Generate Implementation — 2026-08-15T03:22:00.000Z

Implementation complete. Summary:

## File list (all under `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py` (foreground, `0.0.0.0:$PORT`, default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, blueprint registration, `ApiError`/404/405/400 handlers
- `db.py` — in-memory dicts (one per entity, keyed by UUID), logical clock (boots at exactly `2026-08-01T00:00:00Z`, never wall-clock), ID/request-ID generation, ISO-8601 timestamp formatting (3 fractional digits, `Z`), `age_years_on` (floor of days/365.25), per-site order-number sequence
- `errors.py` — `ApiError` class + all 29 error-ID constants from SCAFFOLD §1.6
- `response.py` — envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta gains `limit`/`offset`/`total_count`/`has_more`), pagination parsing (default 10, min 1, max 100, offset ≥ 0)
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction (priority 1 → `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` 400), role membership (priority 2 → `ERR_INSUFFICIENT_PERMISSIONS` 403); three roles exactly as scaffold
- `routes/` — one module per resource group: `provider_sites`, `storage` (units/readings/excursions), `products_lots`, `patients_screenings`, `doses`, `orders` (orders/lines/receipts), `borrow_tickets`, `transfers`, `audits`, `clock`
- `services/ledger.py` — accountability-balance recomputation (provisional: counts INITIATED transfers; final audit snapshot: only IN_TRANSIT/RECEIVED), private-lending balance, audit snapshot, tiered wastage rate (Decimal, 4dp ROUND_HALF_UP, tier on unrounded rate), clock-advance expiration sweep
- `services/excursions.py` — excursion open/peak-update/close, resolve-viable, resolve-wasted (with per-lot write-off and public-portion tracking)
- `services/validate.py` — typed field validators (`ERR_INVALID_REQUEST` vs `ERR_INVALID_ENUM`), existence helper, enum sets

## Architecture highlights

- **State machines** — all seven implemented with exact preconditions and side effects: ProviderSite (suspend/reinstate/terminate with excursion→ticket→audit blocking order and lot cascade to WASTED_CLOSED), Lot (quarantine/release/write-off/deplete/expire cascades, each bumping `version`+`updated_at`), TemperatureExcursion (OPEN→UNDER_REVIEW gated on `closed_at` non-null with `ERR_EXCURSION_STILL_OPEN`; viable/wasted resolutions), VaccineOrder (submit/approve/cancel plus automatic PARTIALLY/FULLY_RECEIVED on receipt posting), BorrowTicket (payback self-loop, auto-REPAID, void with IOU-intact check), SiteVisitAudit (begin/issue-findings with frozen snapshot, close-pass three-condition gate, close-fail suspends site ordering), ShortDateTransfer (ship decrements, receive merges into existing AVAILABLE destination lot or creates successor), DoseAdministration registry lifecycle including the REJECTED→PENDING resubmission loop.
- **Calculations** — VFC eligibility (age floor via days/365.25 AND category set), accountability reconciliation (both provisional and final-snapshot variants), private lending balance (PUBLIC_FROM_PRIVATE OPEN/PARTIALLY_REPAID only), excursion peak by max-deviation comparison (strictly-greater replacement), duration in floored whole minutes, write-off sums, proportional default allocation with remainder to the last line, over-receipt guard, tiered wastage rate.
- **OCC** — exactly the two guarded writes: order approve checks `expected_provider_site_version` against site `version` (412 `ERR_STALE_VERSION`, checked before state per PRD §2.12), payback checks `expected_borrow_ticket_version`; both bump the parent's version on success.
- **Validation ordering** — auth (400) → role (403) → existence left-to-right path then body (404) → OCC (412) → state (409) → business rules in PRD §3 order (dose administration runs quarantine → lot-available → expiry → stock/outcome → screening-match → age → stock exactly as §3.6).
- **RBAC** — three roles; writes restricted per §1.7 (StateProgramOfficer only approves; ComplianceAuditor owns sites/products/audits/clock; VaccineManager owns operations); patients/screenings readable only by ComplianceAuditor+VaccineManager.
- **Logical clock** — boots at the fixed default; `POST /_clock/set_current_utc` (ComplianceAuditor only) advances it and runs the expiry sweep (AVAILABLE + current_date > expires_on + qoh>0 → EXPIRED, zeroed, public lots recompute the ledger).
- **Pagination** — `limit`/`offset` with scaffold defaults; lists sorted by `created_at` ascending; envelope meta carries `limit`, `offset`, `total_count`, `has_more`.
- **Storage** — pure in-memory dicts; nothing seeded at boot; verified empty on fresh launch.

## Boot confirmation

`bash start.sh` boots cleanly in under 2s on a fresh process. Smoke suite (69 checks) passed after correcting my own test arithmetic — verified behaviors include auth/role enforcement, excursion open/quarantine/close/review/resolve (viable and wasted, multi-lot write-off = 84), order submit/approve with OCC 412, allocation mismatch and over-receipt 422s, receipt-created PUBLIC_VFC lots with `received_via_order_id`, full borrow/payback/void lifecycle with IOU and lender restoration, transfer ship/receive with successor-lot creation, audit findings snapshot with RED tier and close-fail cascade suspending the site, termination cascade, clock-advance expiry sweep, and pagination meta.

## Step 5: Generate Unit Tests — 2026-08-15T03:45:00.000Z

Generation complete. All checks pass.

## File lists

**test_helpers/** (all absolute paths under `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/`):
- `test_helpers/__init__.py` — barrel export (framework generics + PRD-specific)
- `test_helpers/types.py` — 15 entity TypedDicts (TemperatureReading correctly omits `updated_at`/`version`), 16 status/role enums
- `test_helpers/api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~60 methods), module-level `api_client`
- `test_helpers/api_errors.py` — all 29 error IDs with HTTP statuses, registered via `set_error_http_status_map`
- `test_helpers/assertions.py` — per-entity `assert_*` + `assert_site_visit_audit_snapshot` (gap arithmetic invariant)
- `test_helpers/factories.py` — payload factories with per-test unique pins/ndc/lot numbers
- `test_helpers/constants.py` — clock boot value, fridge bounds, tier floors, shared dates
- `test_helpers/test_users.py` — three opaque role headers + `NO_AUTH_HEADERS` (no entity_backed roles exist, so no per-instance builders needed)
- `test_helpers/fixtures.py` — composite helpers: order pipeline (`make_approved_order`, `post_receipt`, `make_public_lot(s)`), `make_clinic`, `make_screened_patient`, `administer_dose`, excursion open/close/resolve, `setup_open_borrow`, `record_payback_ok`, transfers, audit lifecycle, `set_clock`

**test_suite/**: `conftest.py` + 7 files:
- `test_01_provider_site_lifecycle.py` (13 tests), `test_02_temperature_excursions.py` (13), `test_03_lots_and_catalog.py` (5), `test_04_orders_and_allocation.py` (11), `test_05_patients_eligibility_doses.py` (19), `test_06_borrow_tickets.py` (12), `test_07_transfers_audits.py` (8)

## Test counts
- **Queue A (Difficulty): 37 tests** covering all 18 instances (≥2 each; `payback_remaining_boundary_exact_remaining_closes_ticket` has 3 — exact-remaining closes, remaining+1 rejected, post-REPAID rejected)
- **Queue B (Corner): 44 tests** covering all 44 non-stub instances (1 each)
- Total: 81 tests, all collected by pytest cleanly

## Skip list
- **Corner/errors/error_excursion_still_open_already_covered** — `excluded_because` stub, not translated; cross-reference verified resolving to the non-stub corner instance `temperature_excursion_begin_review_blocked_while_still_open`.
- **Partial assertion drop (Difficulty/combinatorial_formula/tiered_wastage_rate_boundary_rounding)**: the tier/rounded-rate value is not assertable — neither PRD §3.9 nor the audit entity names a response field for the tier, so a PRD-only implementer could omit it (computed-field silence pattern). The instance's two tests instead pin the PRD-named snapshot fields (received=21, administered=1, wasted=20, gap=0, on_hand=0), which are verbatim-covered.
- **Corner/entities/provider_site_creation_defaults_status_active**: the recipe's `version == 1` sub-assertion was dropped (PRD §2.4 defines version semantics but never states the initial value); the PRD-covered defaults (status=ACTIVE, three counters = 0) are asserted.
- **Corner/errors/error_allocation_mismatch_on_order_approval**: the recipe's literal trigger (`line_allocations: []` expecting `ERR_LINE_ALLOCATION_MISSING`) is two-reader ambiguous (empty-list vs omitted). Translated per the instance's own distinguishing aspect instead: `line_allocations=[{order_line_id, approved_doses: 5}]` with `approved_vfc_doses=99` → `ERR_ALLOCATION_MISMATCH` (PRD §3.5 verbatim).
- No other skips; no `skip`/`skipif`/`xfail` markers anywhere.

## Stage 2 self-check verdict
- **Tag audit: PASS** — every one of the 81 tests ends its docstring with exactly one `Design:` line resolving to a real instance; all 18 difficulty instances ≥2 tests; all 44 non-stub corner instances ≥1; the stub was not translated.
- **PRD-citation verbatim check: PASS** — automated sweep confirmed every test docstring contains a ≥8-word quote that survives whitespace-normalized literal matching against `PRD.md` (5 initially elided citations were rewritten to full verbatim sentences and re-verified).
- **Two-reader spot checks**: priority-order tests (expired-lot state-vs-date, quarantine-vs-over-receipt, adult-patient mismatch-vs-age) rest on explicitly ordered check lists in PRD §3.6/§2.12/§3.7; OCC tests on §2.8; snapshot divergence on §2.7 vs §3.9.
- `pyflakes` clean on test_suite; no "scaffold" references in generated code.

## Step 7: Run Tests and Iterate — 2026-08-15T04:05:00.000Z

All 8 parallel rounds pass 81/81 with zero failures. Exiting with the summary.

---

## Summary

- **Iterations run**: 2 (iteration 1: baseline sweep → 80/81 in all 8 rounds, single deterministic failure; iteration 2: post-fix sweep → 81/81 in all 8 rounds, zero flakes).

- **Tests deleted**: none. The one failing test survived the full diagnostic protocol:
  - `test_07_transfers_audits.py::TestAccountabilitySnapshotVariants::test_provisional_balance_counts_initiated_transfer` — STEP 1a coverage: PRD §2.7 states verbatim "This running, provisional view counts transfers that have been initiated but not yet shipped, and it counts nothing from excursions that are still open, since no write-off exists yet." STEP 1b unique derivability: 14 received − 1 administered − 3 INITIATED-transfer doses = 10 is uniquely determined by that sentence. STEP 2: test setup and assertion faithfully express the PRD rule.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**: none.

- **Fixes applied to `implementation/`** (both in `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/implementation/routes/transfers.py`):
  1. `create_transfer` — added `recompute_accountability_balance(site["id"])` when the source lot is `PUBLIC_VFC`. The stored provisional ledger previously only recomputed on receipt/administration/write-off/expiry/shipment, so it never reflected an INITIATED transfer even though PRD §2.7 requires the provisional view to count initiated-but-unshipped transfers. This was the root cause of the 13-vs-10 assertion failure.
  2. `cancel_transfer` — added the same recompute when cancelling an INITIATED transfer of public stock: a cancelled transfer is no longer "initiated but not yet shipped", so the provisional ledger must stop deducting it (PRD §2.7's "recomputed incrementally on every event that touches any of its terms").

Orchestrator note: the subagent's results files were cleaned up at exit; orchestrator re-ran the full 8-round parallel sweep after Step 7 completion — all 8 rounds 81/81 passed, 0 failed (results.1–8.json regenerated under workspace/implementation/).

## Step 8: Finalize PRD — 2026-08-15T04:12:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/PRD_FINALIZED.md` written.

## Line counts / delta
- PRD.md: 341 lines, 55,636 chars
- PRD_FINALIZED.md: 341 lines, 55,674 chars
- Delta: 0 lines (0.0%); +38 chars (+0.068%). Exactly one in-place sentence revision.

## Changes
- **§2.7 — revise —** the provisional-ledger recompute-trigger enumeration was extended from "...and public-stock transfer shipment" to "...and **the initiation, shipment, or cancellation of a public-stock transfer**". The old enumeration named only shipment as the transfer-related trigger while the next sentence required the provisional view to count INITIATED-but-unshipped transfers; since the site balance is stored and recomputed incrementally (not computed on read), an implementer reading the enumeration as the complete trigger set reproduces the exact stale-balance bug Step 7 fixed. The revision makes initiation (adds to the transferred-out term) and cancellation (removes it) explicit triggers. Covers both Step 7 implementation fixes — `implementation/routes/transfers.py:79-80` (`create_transfer`, initiation recompute) and `implementation/routes/transfers.py:252-254` (`cancel_transfer`, cancellation recompute).

## Per-edit pre-edit search log
- **Edit 1 (the only edit):**
  - (a) **Subject:** the set of events that trigger recomputation of a site's provisional `accountability_balance_doses`, specifically transfer-lifecycle events.
  - (b) **Impl paths enumerated and read/grepped** (full `recompute_accountability_balance` call-site set, confirmed by repo-wide grep): `routes/orders.py:408` (allocation receipt posting), `routes/doses.py:137` (public-funded administration, guarded on `PUBLIC_VFC`), `services/excursions.py:122` (resolve-wasted cascade when a public lot was written off), `services/ledger.py:194` (expiration sweep of public lots), `routes/transfers.py:80` (initiation, guarded on `PUBLIC_VFC`), `routes/transfers.py:165` (shipment, guarded), `routes/transfers.py:254` (cancellation from INITIATED, guarded). Also read and accounted for: `routes/transfers.py:170-237` (`receive_transfer` — performs **no** recompute; under the provisional variant a RECEIVED transfer was already counted while INITIATED/IN_TRANSIT, so the transferred-out term's value is untouched at receipt), `services/ledger.py:84-112` (provisional vs. snapshot variants; `include_initiated=True` only for the provisional balance), and negative checks confirming `borrow_tickets.py`, `provider_sites.py` (termination cascade), and `products_lots.py` never touch this ledger.
  - (c) **Wording adjustment:** chose "the initiation, shipment, or cancellation of a public-stock transfer" — deliberately omitting *receipt* (no recompute in `receive_transfer`, so naming it would fabricate a new mismatch) and keeping the public-stock scope to match the `stock_type == "PUBLIC_VFC"` guard present at all three transfer call sites. The trailing provisional-view sentence and §3.8's shipment-side recompute note remain verbatim and are now mutually consistent.

No other Step 7 items existed (no test deletions, no test_helper/test_suite fixes), and no other edits were made — everything else in the PRD already uniquely determines the implementation's behavior at the Step 7 sites.

## Step 9: Complete PRD — 2026-08-15T04:25:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1948_vaccine_inventory_vfc_program_management/workspace/PRD_COMPLETED.md` produced.

**Source vs output:** `PRD_FINALIZED.md` (341 lines / 55,674 chars) → `PRD_COMPLETED.md` (341 lines / 60,015 chars). Char delta **+4,341**; 25 existing lines revised inline, **0 lines added or removed** (all pins are in-paragraph inserts; no new sections).

**Counts:** 28 ambiguity-pins, 5 mismatch-revisions (33 pinned behaviors across 29 edits).

**Mismatch revisions (PRD asserted behavior impl does not exhibit):**
- §3.1 — revise — mismatch — `vfc_pin` "unique across all sites" → uniqueness is a data expectation; enrollment accepts duplicates (impl: `routes/provider_sites.py:29-50`, no uniqueness check)
- §3.2 — revise — mismatch — `ndc_code` "unique across the catalog" → duplicates accepted without error (`routes/products_lots.py:35-60`)
- §3.4 — revise — mismatch — `lot_number` unique per (product, stock_type) → server does not enforce; duplicates accepted (`routes/products_lots.py:113-158`, no check)
- §3.5 — revise — mismatch — order line `approved_doses` "initially zero" → initially **null** (`routes/orders.py:158`)
- §3.9 — revise — mismatch — `public_doses_wasted` appositive equated it with excursion `doses_written_off` → only the public-stock portion of each wasted resolution counts (private lots in the same excursion excluded) (`services/ledger.py:58-68`, `services/excursions.py:111-112`)

**Ambiguity pins (PRD silent, now pins impl behavior):**
- §2.1 — insert — unrecognized role name is a syntactically invalid header → 400, not 403 (`middleware.py:32-33`)
- §2.3 — insert — non-integer/out-of-range `limit` and non-integer/negative `offset` → `ERR_INVALID_REQUEST` (`response.py:50-75`)
- §2.3 — insert — `has_more` true exactly when `offset` + page size < `total_count` (`response.py:29`)
- §2.3 — insert — `created_at` sort ties broken by `id` ascending (all route files, e.g. `routes/orders.py:118`)
- §2.4 — insert — absent/malformed/non-object JSON body → `ERR_INVALID_REQUEST` (`services/validate.py:11-14`, `app.py:54-61`)
- §2.9 — insert — boolean filters accept `true`/`false` case-insensitively; other values leave the filter unapplied (`routes/products_lots.py:63-71`, `routes/patients_screenings.py:77-85`)
- §2.11 — insert — temperature values accepted as any JSON number, stored unchanged; 1-decimal is convention, not validation (`services/validate.py:52-56`)
- §2.12 — insert — body field validation runs after path-id resolution, before body-id resolution, except where §3 states otherwise (pattern across all route files)
- §3.2 — insert — server does not validate ordering of `min_temp_c`/`max_temp_c` (`routes/storage.py:64-88`)
- §3.3 — insert — further in-range readings while an excursion stays active (incl. `UNDER_REVIEW`) re-set `closed_at` and recompute `duration_minutes` (`routes/storage.py:149-151`, `services/excursions.py:66-72`)
- §3.3 — insert ×2 — `resolution_notes` optional on resolve-viable and resolve-wasted; stored null when omitted (`routes/storage.py:246-248, 258-260`)
- §3.4 — insert — initial `quantity_on_hand` may be zero (`routes/products_lots.py:122`)
- §3.5 — insert — `order_number` format: `ORD-` + zero-padded six-digit per-site sequence from `ORD-000001` (`db.py:117-120`)
- §3.5 — insert — adding a line requires `DRAFT` (`ERR_INVALID_STATE`), checked before line-field/product validation (`routes/orders.py:142-147`)
- §3.5 — insert ×2 — `approved_vfc_doses` may be zero; `line_allocations` shape (id→dose map or list of `{"order_line_id","approved_doses"}`), values non-negative int (`ERR_INVALID_REQUEST`), entries for foreign lines ignored (`routes/orders.py:226-280`)
- §3.5 — insert — proportional distribution algorithm: lines in creation order, floor shares, last line takes remainder (`routes/orders.py:244-263`)
- §3.5 — insert ×2 — receipts accepted only while `APPROVED`/`PARTIALLY_RECEIVED` (`ERR_INVALID_STATE`); quarantine check precedes unit-site check (`routes/orders.py:340-348`)
- §3.6 — insert — patient creation payload may carry `is_active`, default true (`routes/patients_screenings.py:55-58`)
- §3.6 — insert — a ticket "covers" a dose when it is `OPEN` and names the dose's lot as `from_lot_id` or `to_lot_id` (`routes/doses.py:79-85`)
- §3.7 — insert — paying-lot stock_type mismatch rejected with `ERR_SAME_STOCK_BORROW` (`routes/borrow_tickets.py:205-207`)
- §3.7 — insert ×2 — payback and void restore the lender lot's `quantity_on_hand` without resurrecting its `status` (`routes/borrow_tickets.py:222-227, 264-266`)
- §3.8 — insert — initiation itself requires source lot `AVAILABLE` with ≥ `quantity_doses` (`ERR_LOT_NOT_AVAILABLE`/`ERR_INSUFFICIENT_STOCK`), re-checked at shipment (`routes/transfers.py:53-57`)
- §3.8 — insert — receive enforces its two checks in stated order: unit-site mismatch, then quarantine (`routes/transfers.py:183-187`)
- §3.8 — insert — transfer-created successor lot's `received_via_order_id` is null (`routes/transfers.py:227`)
- §3.9 — insert — audit snapshot/rate fields remain null until findings are issued (`routes/audits.py:57-64`)
- §3.9 — insert — issue-findings requires `IN_PROGRESS` → `FINDINGS_ISSUED`, else `ERR_INVALID_STATE` (`routes/audits.py:135-136`)

Everything else in the implementation (endpoint set, RBAC roles, state machines, ledger formulas, sweep semantics, check orderings for dose administration/payback/termination/close-pass, OCC scope, envelope shape, 201/200 discipline) was already uniquely pinned by the PRD and left untouched.
