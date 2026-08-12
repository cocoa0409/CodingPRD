# Worklog — task_1236_building_materials_reuse_warehouse

## Step 1: Create task directory — 2026-08-12T04:20:00.000Z

Pre-assigned output folder `tasks/task_1236_building_materials_reuse_warehouse` with `workspace/` subdirectory already existed on disk; treated Step 1 as done (no auto-index scan run, per instructions).

Scenario: Building Materials Reuse Warehouse (Habitat ReStore style reuse center): donation acceptance criteria & deconstruction pickup scheduling, item pricing & inventory by category, tax receipt & appraisal guidance for donors, hazardous material screening (lead/asbestos) on salvage, volunteer/paid crew for deconstruction jobs, store merchandising & turnover of slow items, contractor account & bulk purchases, diversion tonnage reporting.

Difficulty parameter: "generate task hard than expert level!" — passed through to Step 2 (prd-bench-scaffold-generator) only.

## Step 2: Generate scaffold — 2026-08-12T05:12:00.000Z

Step 2 scaffold generation for task_1236 is complete and lint-clean.

**Output files** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1236_building_materials_reuse_warehouse/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level `scaffold_difficulty_design:`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level `scaffold_corner_design:`

**Counts**: 19 entities, 108 endpoints (incl. `POST /reuse/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`), 86 errors, 15 calculations, 15 state machines, 12 ordered validation priorities, 2 OCC concurrency rules, 9 roles. Lint: **VERDICT: clean lint** — 684 recipe calls scanned across 27 §1.8 + 45 active §1.9 instances, zero violations (endpoint/role/payload/capture/OCC/FK-reverse-reachability all conform).

**Difficulty rules exercised** (all above the ≥2 minimum, fully differentiated):
- dual_variant_calc ×3 — receipt valuation (guidance vs item-sum vs appraisal), job tonnage (estimated vs certified), sale discount (snapshot vs live tier)
- combinatorial_formula ×3 — mode (a) multi-input price stack, mode (b) pinned per-line→sum→discount→tax rounding (797 vs 796 divergence), mode (c) tier-snapshot evaluation order
- non_linear_state_machine ×3 — offer review cycle, Item parallel pricing×sales axes, job hazmat remediation cycle
- transitive_cascade ×2 — finalize chain depth 4 (sale→item→zone→account→agreements), weigh chain depth 3 (batch→job→open report)
- priority_pair_validation_conflict ×3 — state/fiscal, safety/constraint, constraint/temporal
- boundary_precision_check ×4 — appraisal $5000.00 `>=`, zone capacity `==`, markdown day `>=`, SILVER volume 2500000 `>=` (distinct metrics and endpoints)
- cross_entity_state_dependency ×4 — Sale→Account, Job→Screening, Receipt→Offer, Offer→Appointment
- resource_temporal_overlap ×2 — crew half-open (adjacent legal) vs vehicle 60-min buffered (touching illegal)
- compensating_invariant ×3 — zone occupancy, account outstanding balance, certified tonnage under quarantine/remediate cycle

**Notable design decisions**: flat topology with all-FK linkage (all 30+ FKs reverse-reachable via filtered-list GETs); compliance/audit primary archetype with segregation_of_duties role model (receipt issuer ≠ receiver; screener ≠ job lead); polymorphic `PickupAppointment.subject_id`; two self-referential chains (TaxReceipt amend-supersede, Item split lineage); OCC create-with-supersede on both BulkPurchaseAgreement (guards ContractorAccount.version) and TaxReceipt amend; DiversionReport close as the ops-run checkpoint with frozen totals; two deliberate negative-test conveniences (zero-credit account rejects at finalize, positive-limit breaches post-then-auto-suspend). All formula-derived asserts are precomputed literals (e.g., 135000/540000/600000 tri-variant receipt values; 96300 cascade total; 101650 SILVER total). One scaffold bug was caught during self-review and fixed: the report-close gate on unweighed batches now keys on MANIFESTED status globally, since unweighed batches carry no report_period yet.

## Step 3: Copy shared files — 2026-08-12T05:13:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_1236_building_materials_reuse_warehouse/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-12T05:36:00.000Z

**Output**: `workspace/PRD.md` — 460 lines.

**Section structure** (domain-derived, not templated):
- §1 Introduction — 2 paragraphs (business flow of a reuse warehouse + enforcement of segregation-of-duties as the API's raison d'être)
- §2 Global Specifications — 10 subsections: 2.1 Roles (with all 9 roles' `identity:` bindings translated to prose), 2.2 Response Structure (byte-verbatim from `section-2.2-response-structure.md`, diff-verified), 2.3 Pagination, 2.4 Logical Clock (default `2026-05-01T00:00:00Z`, lazy agreement expiry), 2.5 Common Resource Properties (incl. the three `common_fields: false` entities — HazmatScreening, MarkdownRun, SaleLineItem — explicitly lacking `updated_at`/`version`), 2.6 Money/Weight/Rounding, 2.7 OCC (both rules with exact write endpoints, `expected_account_version`/`expected_receipt_version`, 412 error ids), 2.8 Referential Integrity (all 19 per-resource 404 ids named), 2.9 Diversion Ledger principle, 2.10 Validation Cascade (all 12 priority tiers in explicit numbered order)
- §3 Business Logic — 9 subsections organized by material lifecycle: donor registry/recognition → offer pipeline → receiving/tax receipts → deconstruction jobs/screening → crew/fleet/pickups → salvage batches/tonnage → item intake/pricing → sales floor/markdowns → checkout/trade accounts/period close
- §4 Endpoint table — 108 rows, 4 columns, roles byte-matched to scaffold
- §5 Error catalogue — 86 rows, 2 columns, statuses byte-matched to scaffold

**Hard-contract results:**
- *Contract 1 (field-name coverage)*: PASS — 156/156 entity fields, 114/114 endpoint input/query identifiers, 19/19 path params present in backticks (verified mechanically against parsed SCAFFOLD.yaml; two repair passes were needed: splitting composite interval tokens like `[start_at, end_at)` into individually backticked names, and stripping fenced code blocks before token extraction)
- *Contract 2 (rule coverage)*: PASS — all 12 validation priority tiers ordered in prose; both OCC rules fully expressed (endpoint + expected-version field + exact error id + 412); all state-machine transitions across 15 state machines walked (including all 7 job-cancel and 4 offer-cancel sibling edges with equal density); all 15 calculations rendered as reconstruction-safe prose (per-line-rounding-first pinned order, markdown exponent on list price, appraisal verbatim path, batch/walk-in stream separation, half-open vs 60-minute-buffered overlap asymmetry); all 86 catalog error ids mentioned in §1–§4 prose; compensating invariants (finalize+void on zones and balances) stated
- *Contract 3 (§3 path purity)*: PASS — 938 backticked tokens in §3 scanned, 0 path tokens, 0 bare-method tokens, 0 method+path tokens

**Design decisions**: (1) grouped §3 by material lifecycle rather than role or entity, since the domain is a pipeline (donate → screen → weigh → price → sell → report); (2) placed the Category policy entity's full field set in §3.2 (offer acceptance context) so markdown constants could be re-referenced from §3.8, satisfying cross-subsection parameter scattering; (3) converted money constants to dollars-with-cents forms ("$5,000 (500,000 cents)") and rate constants to percent prose ("thirty percent thrift-value rate", "seven percent sales-tax rate") per the embedding guidance; (4) named the two OCC endpoints with literal paths in §2.7 (permitted — purity polices §3 only) while §3 refers to them by capability; (5) `ERR_INVALID_WEIGHTS` appears only in §3.6 prose, not §5, since it is referenced by the weigh transition but absent from the scaffold's `errors[]` catalog — a faithful bi-directional projection.

## Step 5: Generate unit tests — 2026-08-12T06:12:00.000Z

**Tests emitted: 99 total**
- **Queue A (Difficulty): 54 tests** — all 27 instances × 2 tests each (dual-variant facets: rejection/error facet + success/value facet per instance), each tagged `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner): 45 tests** — all 45 non-stub instances × 1 test each, tagged `Design: Corner/<section>/<instance.name>`.
- **Stubs NOT translated (3):** `finalize_side_effects_covered_by_difficulty`, `screener_cannot_lead_covered_by_difficulty`, `cascading_and_dual_variant_layers_covered_by_difficulty` — all `difficulty_instance` cross-references verified to resolve.
- **Instances skipped: 0** — every non-stub instance in both queues passed the PRD-first two-condition filter (verbatim PRD coverage + unique derivability).

**Helper files created** (`test_helpers/`, 9 files, all importing cleanly):
- `types.py` — 27 status enums + 19 entity TypedDicts; the three lean records (HazmatScreening, MarkdownRun, SaleLineItem) omit `updated_at`/`version` per PRD §2.5.
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (74 methods) + module singleton.
- `api_errors.py` — 76 `ApiErrorId` members + HTTP status map registered via `set_error_http_status_map`. Note: `ERR_INVALID_WEIGHTS` appears in PRD §3.6 prose but has no HTTP status anywhere (missing from PRD §5 table), so it is in the enum but deliberately absent from the status map; no test asserts it. `ERR_UNWEIGHED_BATCHES_IN_PERIOD` (PRD §3.9 prose, missing from §5 table) is mapped to 409 per the design index and used by one corner test.
- `assertions.py` — per-entity shape assertions (lean-record absence checks for the three append-only types) + zone-occupancy / account-balance invariant checkers.
- `factories.py` — 16 payload factories, input fields only, sequence-unique codes.
- `constants.py` — PRD thresholds (appraisal 500000, tiers, tax 0.07, pickup fee 5000, buffer 60 min, etc.).
- `test_users.py` — shared constants for the 5 opaque roles + per-instance `make_*_headers` builders for all 9 roles (entity-backed: Donor/Contractor/HazmatTechnician/CrewLead).
- `fixtures.py` — ~30 composite helpers: offer pipeline to ACCEPTED/RECEIVED, issued receipts with priced item sets, cleared/scheduled/in-progress job chains, weighed-batch scenarios, contractor sales with lines, trailing-volume accumulation, OCC-safe agreement creation, pickup booking.
- `__init__.py` — barrel export (framework + PRD-specific).

**Test files** (`test_suite/`, 12 files + `conftest.py`): `test_01_donation_offers`, `test_02_tax_receipts`, `test_03_deconstruction_jobs`, `test_04_salvage_batches_tonnage`, `test_05_items_pricing`, `test_06_zones_markdown`, `test_07_sales_checkout`, `test_08_accounts_agreements`, `test_09_logistics_crew_fleet`, `test_10_diversion_reports`, `test_11_security_access`, `test_12_registry_basics`.

**Verification results:**
- `py_compile` clean on all 22 files.
- `pytest --collect-only`: **99 tests collected**, 0 errors.
- Tag audit (parsed against both design yamls): every test has exactly one Design line; all 99 tags resolve to real instances with correct rule/section; ≥2 per difficulty instance; ≥1 per non-stub corner instance; no stub translated; no broken stub pointers.
- PRD verbatim check: all 146 `PRD §x.y: "..."` citation spans survive whitespace-normalized literal grep of PRD.md (en-dash/U+2212 sentences copied byte-exact).
- No `pytest.mark.skip`/`skipif`/`xfail` markers; no "scaffold" references in generated code comments/docstrings.

## Step 6: Generate implementation — 2026-08-12T06:13:00.000Z

**Files created** (all under `workspace/implementation/`):
- `start.sh` — executable; guarded dependency install (`python3 -c "import flask"` check so per-test reboots skip pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0,<4.0`
- `app.py` — Flask bootstrap, blueprint registration, ApiError/404/405/500 envelope handlers
- `db.py` — in-memory dict stores + logical clock (default exactly `2026-05-01T00:00:00Z`) + `base_fields`/`lean_fields`/`touch`
- `errors.py`, `response.py`, `util.py` — error catalog, `meta`/`response_type`/`data` envelope, datetime/Decimal/validation/pagination/auth helpers
- `services.py` — all §1.3 calculations and recompute/cascade helpers
- `routes_core.py` (clock, donors, categories), `routes_offers.py` (offers, tax receipts), `routes_jobs.py` (jobs, screenings, batches), `routes_store.py` (items, zones, markdown runs), `routes_trade.py` (accounts, agreements, sales, sale lines), `routes_fleet.py` (crew, assignments, vehicles, appointments, diversion reports)

**Route-count verification:** diffed Flask `url_map` (excluding Flask's `/static`) against the SCAFFOLD.yaml §1.5 endpoint table: **108 vs 108, exact match — no missing, no extra** (method, path) pairs. (Independently re-verified by orchestrator: 108 declared vs 108 registered, missing=[], extra=[].)

**Key design decisions:**
- *Validation pipeline* follows PRD §2.10 literally: request shape (400) → auth (401) → role (403) → ownership (403) → path existence (404) → body-FK existence (404) → OCC (412) → state (409) → hazmat/SoD safety → business constraints → temporal → fiscal → referential. Consequences: OCC precedes the ISSUED-state check on receipt amend; vehicle-overlap (9) precedes window validity (10) on schedule/appointment create; agreement window (10) precedes credit/payment (11) at finalize.
- *Clock:* single logical clock, never wall-clock; the set endpoint echoes the raw input string as `current_utc` and stores the parsed UTC datetime for all math (days_on_floor, trailing-365d windows, report periods, receipt year, lazy agreement expiry).
- *OCC:* `expected_account_version` on POST /reuse/bulk-agreements and `expected_receipt_version` on receipt amend, both mandatory; agreement create bumps the parent account version by exactly 1; amend supersedes and bumps the old receipt.
- *Rounding:* `Decimal` + `ROUND_HALF_UP` at exactly the specified steps — per-line totals before subtotal summation, discount/tax rounded after their subtractions, markdown exponent applied to list price with `max(floor, step)` clamp, minimum list price 100 cents; weights held as Decimal at 1-decimal precision.
- *Derived-on-read without version bump:* zone occupancy/restock, item days_on_floor, OPEN report totals (CLOSED frozen at close), donor/account trailing windows and tiers; lazy agreement EXPIRED flip bumps version per the state machine. Internal bookkeeping fields (`_disposed_at`, `_reserved_zone_id`, `_year`) are stripped from serialization; HazmatScreening/MarkdownRun/SaleLineItem carry only `id` + `created_at`.
- *Catalog gaps:* `ERR_INVALID_WEIGHTS` and `ERR_UNWEIGHED_BATCHES_IN_PERIOD` are referenced by state machines but absent from §1.6/§5 — assigned HTTP 400 and 409 respectively.
- *No seeding:* store starts empty; the only `seed` string in the codebase is a docstring; every mutation lives inside a route handler.

**Smoke-test evidence:** 4 suites each run against a freshly booted process (one boot via the literal `bash start.sh` contract) — **144/144 assertions passed** (37 + 43 + 49 + 15), covering the offer pipeline with guidance valuation (15000), pricing engine (18750), walk-in finalize rounding (tax 65625 / total 1003125), void-restock invariant, receipt SoD/amend-OCC/supersede/void cycles with donor-tier recompute, appraisal threshold verbatim valuation (700000 → BUILDER), screening/remediation rounds, screener-cannot-lead, crew half-open vs vehicle 60-minute-buffered overlap (exact-boundary allowed), batch weigh/quarantine/re-credit tonnage divergence, agreement discount `max(tier, agreement)` = 0.15, auto-suspend `CREDIT_LIMIT_BREACH` cascade, markdown boundary-day inclusivity and step pricing (15000 → 11250 → disposition flag), and diversion-report open-recompute/close-freeze.

## Step 7: Run tests and iterate — 2026-08-12T06:24:00.000Z

**Summary**

- **Iterations run:** 2 sweeps (initial diagnostic sweep: 95/99 × 8 rounds, identical 4-test union; post-fix sweep: 99/99 × 8 rounds, all clean).
- **Tests deleted:** none. All 4 failing tests traced to verbatim PRD sentences and uniquely derivable assertions.
- **Fixes applied to test_helpers/:**
  - `test_helpers/api_errors.py` — added missing `ApiErrorId.ERR_UNWEIGHED_BATCHES_IN_PERIOD` enum member (named verbatim in PRD §3 prose at line 249, fixing `test_report_close_blocked_by_manifested_batch`); deliberately kept out of `HTTP_STATUS_CODES` because the error is absent from the PRD §5 catalogue, so no HTTP status is uniquely PRD-derivable and `validate_error` now checks error_id only.
- **Fixes applied to test_suite/:**
  - `test_suite/test_07_sales_checkout.py` — added `api_client as api` to the `test_helpers` import; module-level helper `_setup_suspended_zero_credit_sale()` referenced bare `api` (NameError in both `test_state_error_wins_over_credit_gate` and `test_rejected_finalize_leaves_sale_and_item_untouched`). The conftest `api` fixture returns the same `api_client` singleton, so the import is semantically identical.
  - `test_suite/test_02_tax_receipts.py` — `test_appraisal_threshold_under_boundary_issues_without_appraisal`: fixture arithmetic bug, `[100000] * 2` = 200000 but comment/assertion said 400000; changed to `[200000] * 2` so the item sum (400000) matches the documented intent and stays strictly below the 500000 inclusive appraisal threshold per PRD §3.3.
- **Fixes applied to implementation/:** none — the implementation was correct in all 4 failures (it returned 200000, the true item sum; it already emitted `ERR_UNWEIGHED_BATCHES_IN_PERIOD` with 409).

Orchestrator verification: all 8 results files on disk report passed=99, failed=0, errors=0, total=99.

## Step 8: Finalize PRD — 2026-08-12T06:26:00.000Z

`workspace/PRD_FINALIZED.md` written.

**Line counts / %-delta:** PRD.md = 460 lines; PRD_FINALIZED.md = 461 lines; +1 line (+0.22%).

**Changes:**
- §5 Error Code Catalogue — insert — added row `| ERR_UNWEIGHED_BATCHES_IN_PERIOD | 409 Conflict |` immediately after the `ERR_REPORT_NOT_OPEN` row; the error is named in §3 prose (line 249) but was absent from §5, so its HTTP status was underivable; the implementation emits it with 409 — `implementation/routes_fleet.py:554` (in `close_report`, lines 543-557).

**No other edits.** The two remaining Step-7 items are pure test/fixture bugs with no PRD implication: `test_07_sales_checkout.py` (missing `api` import — NameError in test code only) and `test_02_tax_receipts.py` (`[100000]*2` vs `[200000]*2` fixture arithmetic — PRD §3.3, line 167, already pins the 500,000-cent inclusive appraisal threshold verbatim).

**`ERR_INVALID_WEIGHTS` check:** `implementation/errors.py` assigns it no status; it is raised inline with HTTP 400 at `implementation/routes_jobs.py:511` (weigh) and `:562` (resolve-quarantine). Absent from PRD §5 (named only in §3.6 prose, line 205) — same silence pattern, but does not trace to any Step-7-listed item's subject. Left for Step 9 per instructions.

**Per-edit pre-edit search log (the single edit):**
- (a) Subject: HTTP status for `ERR_UNWEIGHED_BATCHES_IN_PERIOD`, the diversion-report close gate triggered when any salvage batch stands `MANIFESTED`.
- (b) Impl paths enumerated: `implementation/errors.py` (full read); `implementation/routes_fleet.py:492-569` (`close_report` at 543-557 is the sole emission site, status 409); grep `MANIFESTED` across implementation → `routes_jobs.py:319`, `routes_jobs.py:450`, `routes_jobs.py:496-497`, `routes_fleet.py:552`; grep `UNWEIGHED|close_report|diversion-reports` → no other emission site. Sibling gate `ERR_QUARANTINED_BATCHES_OPEN` verified consistent (PRD §5 line 432 = 422; impl `routes_fleet.py:563` = 422), no edit needed.
- (c) Wording adjustment: none beyond placement — inserted row uses the exact two-column form of sibling 409 rows; trigger conditions remain solely in §3 prose, whose wording matches the impl check verbatim.

## Step 9: Complete PRD — 2026-08-12T06:44:00.000Z

`workspace/PRD_COMPLETED.md` produced.

**Size:** PRD_FINALIZED.md 461 lines / 82,578 chars → PRD_COMPLETED.md 462 lines / 85,580 chars (Δ +1 line, +3,002 chars; 27 revised/inserted lines, all in-paragraph; no new sections).

**Counts:** 20 ambiguity-pins, 6 mismatch-revisions.

**Mismatch-revisions:**
- §5 — revise (catalogue completion) — added missing `ERR_INVALID_WEIGHTS` row (HTTP 400) — implementation/routes_jobs.py:511 (weigh), :562 (resolve-quarantine). The known lead, confirmed exactly as reported.
- §3.6 — revise — quarantine no longer claims "with optional `notes` recorded"; impl reads and stores no notes — routes_jobs.py:529-542.
- §3.9 — revise — finalize's attached-agreement gate: not-ACTIVE now fails with `ERR_AGREEMENT_NOT_ACTIVE` (409); `ERR_AGREEMENT_NOT_IN_WINDOW` (422) is only the window breach — routes_trade.py:546-558.
- §3.8 — revise — dispose gate: any state other than `BACKROOM`/`ON_FLOOR` fails with `ERR_ITEM_NOT_BACKROOM` (PRD had implied `ERR_ITEM_NOT_ON_FLOOR` also fired here; impl never raises it from dispose) — routes_store.py:279-292.
- §2.1 — revise — CrewLead ownership binding scoped to job start/complete only; batch manifest/weigh and reads carry no per-job ownership check — routes_jobs.py:48-50, 221, 243 vs. 426-526.
- §2.10 step 9 — revise — business-constraint list extended with `ERR_CATEGORY_NOT_ACCEPTING`, `ERR_NO_CREW_ASSIGNED`, `ERR_INVALID_WEIGHTS` (all raised post-state, pre-temporal in impl) — routes_offers.py:201, routes_jobs.py:228, 505-514.

**Ambiguity-pins:**
- §2.1 — insert — Donor/Contractor passing a foreign `donor_id`/`contractor_id` list-filter value is refused with `ERR_NOT_RESOURCE_OWNER` — routes_offers.py:123-124, 399-400; routes_trade.py:293-294, 411-412.
- §2.5 — insert — `version` starts at 1 — db.py:71.
- §2.8 — insert — body-FK enumeration extended with `allowed_category_id` (→ category not-found) and `deconstruction_job_id` (→ job not-found) — routes_store.py:367-368, routes_offers.py:75-76.
- §3.2 — insert — category `acceptance_status` change outside the four legal edges fails with `ERR_INVALID_REQUEST`; categories list filters on `acceptance_status` — routes_core.py:237-242, 203-205.
- §3.4 — insert — screenings list filters `job_id`/`performed_by_crew_id`/`outcome` — routes_jobs.py:403.
- §3.4 — insert — cancelling a terminal job fails with `ERR_INVALID_JOB_STATE` — routes_jobs.py:325-328.
- §3.5 — insert — volunteer zero-rate forcing applies on update as well as registration — routes_fleet.py:143-144.
- §3.5 — insert — assignment `hours_worked` must be positive (`ERR_INVALID_REQUEST`) — routes_fleet.py:224.
- §3.5 — insert — assignments list filters `job_id`/`crew_member_id`/`status` — routes_fleet.py:206.
- §3.5 — insert — invalid vehicle status transition → `ERR_INVALID_REQUEST`; vehicles list filters on `status` — routes_fleet.py:338-342, 316.
- §3.6 — insert — batch `estimated_weight_lbs` must be > 0 — routes_jobs.py:432.
- §3.6 — insert — resolve-quarantine `new_scale_weight_lbs` must be > 0 and ≥ recorded `contamination_weight_lbs`, else `ERR_INVALID_WEIGHTS` (400) — routes_jobs.py:557-565.
- §3.7 — insert — item `estimated_weight_lbs` must be ≥ 0 — routes_store.py:67.
- §3.7 — insert — split remainder copies parent's category, provenance links, description, grade, `pre_1978_flag`, and `estimated_weight_lbs` verbatim; born `UNPRICED`/`BACKROOM` — routes_store.py:321-347.
- §3.8 — insert — zone PATCH may also revise `restock_threshold`/`allowed_category_id`; dispose-from-floor also clears `floor_since` — routes_store.py:407-434, 284.
- §3.9 — insert — Contractor caller may open only CONTRACTOR_ACCOUNT sales for own account; a WALK_IN attempt is `ERR_NOT_RESOURCE_OWNER` — routes_trade.py:346-350.
- §3.9 — insert — sale-line quantity: non-positive or above `measure_qty` → `ERR_INVALID_REQUEST`; Contractor restricted to own sales' lines (list and get) — routes_trade.py:435-457, 480-484, 498-501.
- §3.9 — insert — sale-void `void_reason` is optional (recorded when supplied); void also clears `sold_via_sale_id` — routes_trade.py:623, 642.
- §3.9 — insert — `payment_terms_days` ≥ 1 when supplied; account close from a state other than ACTIVE/SUSPENDED → `ERR_INVALID_ACCOUNT_STATE`; payment requires positive `amount_cents` and answers 201 with the updated account — routes_trade.py:69, 173-176, 193-205.
- §3.9 — insert — diversion reports list filters on `status` — routes_fleet.py:529-531.

Notable deliberate non-changes: list ordering left as "created_at ascending" (impl returns insertion order — identical under the PRD's advance-only clock semantics); OPEN report "recompute on every event" left as-is (impl recomputes lazily on read via `serialize_report`, observably identical); framework fallbacks `ERR_NOT_FOUND`/`ERR_INTERNAL` (app.py 404/500 handlers) intentionally not catalogued in §5, which covers the domain error surface only.
