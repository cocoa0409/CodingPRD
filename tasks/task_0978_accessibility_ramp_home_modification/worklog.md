# Worklog — task_0978_accessibility_ramp_home_modification

## Step 1: Create task directory — 2026-08-09T17:20:00.000Z

Pre-assigned output folder `tasks/task_0978_accessibility_ramp_home_modification` and its `workspace/` subdirectory already exist; Step 1 auto-index scan skipped per headless-run instructions. Difficulty parameter: "generate task hard than expert level!" (passed through to scaffold generator at Step 2 only).


## Step 2: Generate scaffold — 2026-08-10T09:24:00.000Z

Resumed headless run: SCAFFOLD.yaml (2270 lines, §1.0–§1.7: 15 entities, 13 state machines, 3 concurrency rules, 8 calculations, 15 validations, 81 endpoints, 36 errors, 11 roles) already existed from the interrupted attempt but had broken YAML (unquoted `?` optional-markers in flow-sequence `input:` lists). Orchestrator repaired quoting (11+ lines normalized to quoted tokens) — `yaml.safe_load` now passes; content otherwise untouched. SCAFFOLD_DIFFICULTY_DESIGN.yaml and SCAFFOLD_CORNER_DESIGN.yaml were missing; a Step-2-completion subagent generated them from the existing SCAFFOLD.yaml. Verbatim subagent summary:

## Files created

1. **SCAFFOLD_DIFFICULTY_DESIGN.yaml** — single top key `scaffold_difficulty_design:`, **18 instances, exactly 2 per rule**:
   - `dual_variant_calc`: quote per-line vs aggregate rounding divergence + rental calendar-month vs 30-day-block duration divergence (different entity domains: Quote vs RentalRamp)
   - `combinatorial_formula`: mode (a) tiered rental rate x deposit-cap min() interaction (27000/20000) + mode (b) per-line tax rounding order (11+11=22 vs 21 aggregate)
   - `non_linear_state_machine`: InventoryUnit AVAILABLE→MAINTENANCE→AVAILABLE→RESERVED→DEPLOYED cycle + Quote UNDER_REVIEW fork with divergent APPROVED(commits)/REJECTED(releases) side effects
   - `transitive_cascade`: depth-3 inspection-pass→job PASSED→Case INSPECTED→WARRANTY_ACTIVE + depth-2 case-cancel→quote SUPERSEDED→allocations RELEASED
   - `priority_pair_validation_conflict`: state(5) beats business_constraint(6b) → ERR_QUOTE_NOT_DRAFT + business_referential(9) beats business_fiscal(10) → ERR_FUNDING_RESTRICTION_VIOLATION
   - `boundary_precision_check`: funding equality 19999→PARTIALLY vs 20000→FULLY_FUNDED + zero-line-item submit → ERR_QUOTE_EMPTY
   - `cross_entity_state_dependency`: RentalRamp×InventoryUnit gating + Quote×Case ASSESSED gating
   - `resource_temporal_overlap`: interior-intersection overlap on InventoryUnit + interval-precedence FINAL-inspection-after-job-end on Inspection×InstallationJob
   - `compensating_invariant`: commit/reverse conserves remaining_cents == 50000 + send/void conserves case billing ledger at 0

2. **SCAFFOLD_CORNER_DESIGN.yaml** — single top key `scaffold_corner_design:`, **91 instances (83 active + 8 excluded_because stubs)** across all nine guide sections:
   - entities 15, state_machines 23 (22+1 stub), calculations 10 (9+1), validations 10 (6+4), endpoints 4, errors 18 (17+1 — full not-found family, ERR_CASE_NOT_ACTIVE/NOT_FUNDED, ERR_ASSESSMENT_NOT_SCHEDULED, ERR_JOB_NOT_IN_PROGRESS, ERR_INSUFFICIENT_FUNDING, ERR_PAYMENT_EXCEEDS_BALANCE), rbac 4, cross_cutting_complexity_layers 6 (5+1 — all three OCC rules, version-increment, scheduled OVERDUE), consistency_model 1

## Verification results
- Both files parse with `yaml.safe_load` ✓
- 109 total instance names, zero duplicates across the union ✓
- All `grounds:` references resolve to declared SCAFFOLD.yaml §1.1–§1.7 elements ✓
- All `excluded_because.difficulty_instance` citations resolve to §1.8 names; stubs carry no `test_recipe` ✓
- Zero unbound placeholders across all 746 calls ✓
- `scaffold_lint.py`: 0 violations attributable to §1.8/§1.9 calls. The 25 reported violations are all rule (f) FK_REVERSE_UNREACHABLE at the SCAFFOLD level — a pre-existing artifact of the scaffold's `api_prefix: /cases` topology; the authoritative SCAFFOLD.yaml was not modified.

## Step 3: Copy shared files — 2026-08-10T09:26:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0978_accessibility_ramp_home_modification/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T09:38:00.000Z

PRD generation complete. `workspace/PRD.md` exists (354 lines, 57 KB) and passes all three hard contracts. Verbatim subagent summary:

**Section list:** §1. Introduction; §2. Global Specifications — 2.1 RBAC; 2.2 API Response Structure (verbatim block, byte-identical); 2.3 Pagination; 2.4 Resource Identity, Timestamps & OCC; 2.5 Monetary Precision & Rounding; 2.6 Request Validation Order & Error Precedence; 2.7 Nested Resource Addressing; 2.8 Derived Case Totals & Funding Posture; 2.9 Logical Clock & Time-Driven Transitions; §3. Business Logic — 3.1 Intake & Clinical Assessment; 3.2 OT Collaboration; 3.3 Quoting, Revisions & Cost Composition; 3.4 Funding Sources & Draw Waterfall; 3.5 Installation, Permits & Inspection; 3.6 Rental Ramp Program & Inventory Fleet; 3.7 Invoicing, Payments & Billing Cycles; 3.8 Warranty Service & Case Closure; 3.9 Reassessment & Follow-Up; §4. Endpoint Definitions (81 rows); §5. Error Code Catalogue (36 rows).

**Coverage confirmation (machine-verified against SCAFFOLD.yaml):**
- Contract 1 field-name coverage: PASS — 143/143 entity fields, 79/79 request-body identifiers, 13/13 path params, all present verbatim in backticks.
- Contract 2 rule coverage: PASS — all 15 validations with priority ladder in §2.6; all 3 concurrency_rules with `expected_case_version` + `ERR_STALE_VERSION`/412; all 13 state machines' transitions (every from/to pair, precondition, error_id, side effect, incl. cascades); all 8 calculations as precise prose (per-line round-half-up quote math, funding-gap floor at zero + 4 posture boundaries, rental tiers 100/90/80/70% + deposit lesser-of-2-months-vs-20%-of-purchase, ADA weights 25/20/25/15/15, safety risk 0.5·hazards + 0.05·(100−mobility) clamped [0.0,10.0] at 1 decimal, invoice tax, priority_rank→created_at waterfall with NO_RENTAL restrictions, day-prorated billing one-invoice-per-case); all 36 error_ids in §2/§3 prose.
- Contract 3 §3 path purity: PASS — 632 backticked tokens scanned in §3, zero path tokens, zero bare HTTP methods.
- Endpoint table: 81/81 rows match scaffold method+path exactly; roles per row match scaffold. Note: WarrantyClaim `→ CLOSED` transition exists in the state machine but has no endpoint row in the scaffold; the transition is expressed in §3.8 prose while §4 stays at the scaffold's 81 rows.
- All enum values and all 11 role names appear as exact strings.

## Step 5: Generate unit tests — 2026-08-10T10:15:00.000Z

Generation complete. Verbatim subagent summary:

**test_helpers/ (9 files, 1550 lines):** `types.py` (15 entity TypedDicts + 15 status/role enums); `api_client.py` (87 endpoint methods covering every PRD §4 endpoint incl. `/_clock/set_current_utc`); `api_errors.py` (37 ApiErrorId values + HTTP status map); `assertions.py` (per-entity assert_* + case-ledger invariants); `factories.py` (20 payload factories, input fields only); `constants.py` (tier multipliers, deposit cap, risk weights, warranty/billing defaults, clock start); `test_users.py` (10 role header constants — all roles opaque per PRD §2.1); `fixtures.py` (composite helpers: create_assessed_case, create_draft_quote (OCC-threading), setup_submitted/under_review/approved_quote, installation job setups, rental setups, invoice setups, funding/OT/reassessment/warranty helpers); `__init__.py` barrel export.

**test_suite/ (11 files: conftest + 10 test files, 116 tests)** — all collect cleanly under `pytest --collect-only`.

**Queue A (Difficulty): 17 of 18 instances translated, each with exactly 2 tests (34 tests).** Skipped: `cross_entity_state_dependency/rental_lifecycle_gated_by_inventory_unit_state` — lead assertion (rental create against MAINTENANCE unit → ERR_UNIT_UNAVAILABLE) not PRD-covered: PRD §2.6(13)/§3.6 state ERR_UNIT_UNAVAILABLE only for overlapping rental periods; a MAINTENANCE unit has no active rental, so error_id not uniquely derivable (faithful reader could emit ERR_INVALID_STATE_TRANSITION). Whole instance skipped rather than weakened.

**Queue B (Corner): 82 of 83 non-stub instances translated (82 tests).** All 8 `excluded_because` stubs correctly untranslated. Skipped: `validations/third_party_invoice_above_funding_rejected` — PRD §3.7 pins ERR_INVOICE_EXCEEDS_FUNDING guard to invoice creation where total is necessarily zero, while the instance asserts send-time rejection; two readings diverge, failing unique derivability.

**Compliance audit (script-verified):** 116/116 tests carry exactly one valid Design: docstring tag resolving to a real instance; 169 long PRD quotations grep-verbatim against PRD.md; no skip/skipif/xfail anywhere; no scaffold references; all money assertions use PRD-exact `*_cents` field names.

## Step 6: Generate implementation — 2026-08-10T10:15:00.000Z

Generation complete. Verbatim subagent summary:

**Files created** in `workspace/implementation/`: `start.sh` (guarded pip install, `exec python3 app.py` foreground); `requirements.txt` (flask>=3.0,<4.0); `app.py` (Flask bootstrap, envelope error handlers, before_request time-driven transitions); `core.py` (in-memory dict store, logical clock default 2026-05-01T00:00:00Z, response envelope, auth middleware X-User-ID/X-User-Role 10 valid roles, body validators, pagination limit default 10 clamped 1–100, OCC helper); `domain.py` (all calculations, case-ledger recomputation, funding waterfall, state helpers, tick()); `routes/` — 13 blueprint modules.

**Endpoints: 81/81** (orchestrator independently verified: 81 (method, path) route pairs registered, 0 missing, 0 extra vs SCAFFOLD.yaml §1.5).

**State machines: 13/13** — Case (12-state corridor + cancel cascade), Assessment, Quote (revisions/supersede/expire), FundingSource (auto-EXHAUSTED at zero), FundingAllocation, InstallationJob (auto POST_INSTALL reassessment at completion), RentalRamp (unit status coupling, final-invoice on return), InventoryUnit, Inspection (FINAL pass cascades job→PASSED, case→INSPECTED→WARRANT_ACTIVE; FINAL fail reverts job), Invoice, WarrantyClaim (uncovered resolution auto-generates WARRANTY_WORK invoice), OTConsultation, ReassessmentSchedule. Time-driven transitions fire on logical clock at set_current_utc and lazily per request.

**Calculations: 8/8** — quote totals per-line round-half-up (Decimal), contingency ≤25%; funding gap floored at 0 + 4-tier posture; tiered rental rate 100/90/80/70% with deposit min(2×rate, 20% purchase); ADA weighted compliance 25/20/25/15/15; safety risk index clamped 0–10 1dp; invoice tax aggregation; priority-ordered funding waterfall honoring NO_RENTAL/PERMANENT_ONLY; prorated rental billing.

**Concurrency: 3 OCC rules** via expected_case_version → ERR_STALE_VERSION (412) on quote create, funding approve, invoice send (+ invoice create); validation ladder auth→role→existence→case state→target state→body→OCC→business with all 36 catalog error IDs.

**Smoke tests:** clean boot; GET /cases → 200 empty; POST /cases → 201 INTAKE; full lifecycle 45/45 checks; rental/inventory/OT/cancel-cascade 34/34; fresh reboot wipes all state. Server stopped.

## Step 7: Run tests and iterate — 2026-08-10T10:40:00.000Z

Two consecutive clean 8-round sweeps (116/116, zero errors). Exit criteria met. Orchestrator verified on disk: all 8 `results.{1..8}.json` show passed=116 total=116 failed=0 errors=0. Verbatim subagent summary:

- **Iterations run**: 3 sweeps total (1 baseline + 1 after fixes + 2 confirmation sweeps, the last two fully clean: 116/116 × 8 rounds).

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**: none.

- **Fixes applied to `test_suite/`**:
  - `test_suite/test_06_rentals_inventory.py` — `test_rental_return_side_effects_unit_available`: added `set_clock("2026-05-31T00:00:00Z")` after `setup_pickup_scheduled_rental(...)` and before `confirm_pickup`. The fixture previously confirmed pickup with the logical clock frozen at `rental_start` (2026-05-01), making the asserted `total_rental_days > 0` non-deterministic across PRD-faithful readings of "the rental's duration" (PRD §3.6 states the side effect but no duration formula). Advancing the clock (PRD §2.9 capability) makes the duration unambiguously positive under both elapsed-time and booked-period readings.

- **Fixes applied to `implementation/`**:
  - `workspace/implementation/core.py` — `new_id()`: changed `uuid.uuid4().hex` to `str(uuid.uuid4())`. PRD §2.8 declares `id` is "a server-minted UUID"; the dash-less hex form failed the canonical RFC 4122 hyphenated string form the tests assert. Fixed 5 consistently-failing tests (case/assessment/quote UUID assertions).
  - `workspace/implementation/start.sh` — added a `.deps_installed` stamp file so the per-restart dependency check no longer spawns a second `python3 -c "import flask"` interpreter on every boot, plus `PYTHONDONTWRITEBYTECODE=1`. This eliminated the intermittent infrastructure flake where the runner's 15 s readiness window expired under 8-way parallel restart load (~930 server boots per sweep on 8 CPUs), which had been causing random `error on setup` failures (0 assertions involved) in ~2–3 of 8 rounds. Also added a one-line boot trace append for diagnostics (inert, not entity storage).

Final state: all 116 tests pass in all 8 parallel rounds, twice consecutively.

## Step 8: Finalize PRD — 2026-08-10T10:32:00.000Z

Step 8 complete. `workspace/PRD_FINALIZED.md` written (verified on disk, 354 lines). Verbatim subagent summary:

**Line counts:** PRD.md = 354 lines; PRD_FINALIZED.md = 354 lines (0.0% delta — both edits are in-place sentence revisions).

**Changes (2 edits):**
- §2.4 — revise — "`id` is a server-minted UUID" now pins "the canonical RFC 4122 string form — hyphenated 8-4-4-4-12 lowercase hexadecimal" (PRD said "UUID" without pinning the string rendering; `uuid.uuid4().hex` was a PRD-faithful reading) — `implementation/core.py:67-68` (`new_id()` returns `str(uuid.uuid4())`). Note: the Step 7 worklog cited §2.8, but the id-definition sentence actually lives in §2.4.
- §3.6 — revise — confirm-pickup sentence now defines "the rental's duration" as "the number of whole days elapsed between the reservation's `rental_start` and the logical-clock instant at which pickup is confirmed, never less than zero" (PRD stated the side effect but no formula) — `implementation/routes/rentals.py:223-224` (`days = (ts - ramp["_rental_start_dt"]).days`, added via `max(0, days)`).

**No edits for:** the test_06 fixture fix (the `set_clock` change was a test-side determinism fix; the PRD silence it exposed is the duration formula, covered by Edit B) and the start.sh stamp/boot-trace change (pure infrastructure; verified no PRD sentence addresses process startup, dependency caching, bytecode, or diagnostic logs — no contradiction).

**Pre-edit search log:**

*Edit A (id format)* — (a) Subject: string form of the system-managed `id` field on all 15 resource types. (b) Enumerated paths: `core.py:67-68` `new_id()` — the sole minting function; `core.py:367-376` `new_record()` — its only caller; all 21 `new_record()` call sites (cases.py:27, assessments.py:62, quotes.py:53/131, funding.py:35/180, jobs.py:59/192, rentals.py:34/54/112, inventory.py:19, inspections.py:47, invoices.py:67/127, claims.py:44/124/144, ot.py:29, schedules.py:31, domain.py:300) — every resource id flows through this one function, so the universal claim holds. Excluded as unaffected: `request_id()` (core.py:122-123, mints the `req_`-prefixed `api_request_id` governed by §2.2, a different field) and `next_number()` human-readable numbers (separate fields). Test-side evidence: runner's `is_valid_uuid` regex (assertions.py:19-21) — the impl's lowercase hyphenated output matches. (c) No wording adjustment needed.

*Edit B (rental duration at confirm-pickup)* — (a) Subject: how the rental's duration is computed when added to a unit's `total_rental_days` at pickup confirmation. (b) Enumerated paths: `routes/inventory.py:31` (field initialized to 0 at unit creation); `routes/rentals.py:223-224` (sole writer after creation: whole days from `_rental_start_dt` to `now()`, clamped ≥ 0); `routes/rentals.py:125` (`_rental_start_dt` = the reservation's `rental_start`); `routes/rentals.py:26-27` (`_final_invoice_for_unbilled` measures from `_last_billed_dt` — a different quantity under §3.7); `domain.py:204-218` (monthly proration for §3.7 billing — different arithmetic); `domain.py:394-400` (INSTALLED→IN_USE active-window check — unrelated to day accumulation). (c) Wording scoped explicitly to the pickup-confirmation side effect so it makes no claim about §3.7's per-period billing arithmetic.

## Step 9: Complete PRD — 2026-08-10T10:45:00.000Z

Step 9 complete. `workspace/PRD_COMPLETED.md` written (verified on disk, 358 lines, 65,690 bytes). Verbatim subagent summary:

**Files:** Source: PRD_FINALIZED.md — 354 lines, 57,123 chars. Output: PRD_COMPLETED.md — 358 lines, 65,435 chars. Char delta: **+8,312**.

**Counts:** 16 ambiguity-pins, 10 mismatch-revisions (several edits contain both; classified by dominant character).

**Changes (one bullet per logical edit):**
- §2.3 — insert — ambiguity — non-integer limit/offset → ERR_INVALID_REQUEST; out-of-range values clamped (limit→[1,100], offset→≥0) — core.py:336-353
- §2.3 — insert — ambiguity — list sort ties broken by insertion order — core.py:356-362
- §2.4 — insert — ambiguity — missing/non-integer `expected_case_version` → ERR_INVALID_REQUEST before comparison — core.py:414-425
- §2.6 — revise — mismatch — body-field validation (ERR_INVALID_REQUEST) moved from "before the ladder" to a stage between state checks (step 5) and business constraints (step 6); body-referenced resource ids resolve in this stage with their 404; OCC check lives in this stage — routes/*.py uniformly (e.g. funding.py:71-98, quotes.py:30-47, invoices.py:38-65)
- §2.7 — insert — ambiguity — unresolved allocation id → ERR_FUNDING_SOURCE_NOT_FOUND (no separate allocation 404); undefined paths/methods → ERR_NOT_FOUND 404 — funding.py:209-211, app.py:27-36
- §2.8 — revise — mismatch — `total_quoted_cents` = sum of quote `total_cents` over DRAFT/SUBMITTED/UNDER_REVIEW/APPROVED; `total_funded_cents` includes EXHAUSTED sources; `total_billed_cents` covers SENT/PARTIALLY_PAID/PAID/OVERDUE/DISPUTED; `total_paid_cents` = sum of `amount_paid_cents` over those statuses — domain.py:12-14, 44-58
- §2.9 — insert — ambiguity — clock-set rejects bad `to_iso8601` with ERR_INVALID_REQUEST, responds 200 with empty data object; tick re-runs on every request; IN_USE window inclusive of both rental_start and rental_end — clock.py:13-23, app.py:17-19, domain.py:394-400
- §3.1 — insert — ambiguity — new case initializes ada_scope_score/caps_scope_score to 0 and safety_risk_index to 0.0 — cases.py:40-42
- §3.1 — insert — ambiguity — assessment creation allowed from any active case status; INTAKE→ASSESSMENT_SCHEDULED advance only when still INTAKE — assessments.py:44-85
- §3.1 — insert — ambiguity — starting before scheduled_date → ERR_INVALID_STATE_TRANSITION; completing from non-IN_PROGRESS → ERR_INVALID_STATE_TRANSITION — assessments.py:111-126
- §3.1 — insert — ambiguity — completion accepts factor scores entrance_access/interior_circulation/bathroom_access/kitchen_access/bedroom_access with missing factors falling back to mobility_score; `ada_compliance_pct` and `caps_recommendation_score` may be supplied directly; caps defaults to whole-number rounding of ada; `rental_eligible` defaults true, `purchase_required` false — assessments.py:28-41, 133-145
- §3.1 — insert — ambiguity — every assessment completion recomputes case `safety_risk_index` from that assessment's values, independent of the ASSESSED advance; scope scores read from latest completed assessment — assessments.py:160-175
- §3.2 — insert — ambiguity — `clearance_given` supplied in completion request, defaults false — ot.py:74
- §3.3 — insert — ambiguity — quote create accepts optional `discount_cents` defaulting to 0 — quotes.py:47
- §3.3 — revise — mismatch — contingency_pct must be 0–25.0 inclusive, violation → ERR_INVALID_REQUEST 400 — quotes.py:43-46
- §3.3 — insert — ambiguity — quote line `quantity` may be fractional; `unit_price_cents` must be integer — quotes.py:119-121
- §3.3 — insert — ambiguity — submit with expired valid_until → ERR_INVALID_STATE_TRANSITION 409 — quotes.py:165-167
- §3.3 — revise — mismatch — case advances QUOTE_SUBMITTED→FUNDING_PENDING as soon as any funding source is registered, and →FUNDING_APPROVED when approved funding covers the latest SUBMITTED/UNDER_REVIEW (fallback APPROVED) quote — domain.py:75-93, funding.py:51-52
- §3.3 — insert — ambiguity — start-review/approve/reject from wrong state → ERR_INVALID_STATE_TRANSITION — quotes.py:189-191, 202-204, 246-248
- §3.4 — revise — mismatch — restriction codes NO_RENTAL **and PERMANENT_ONLY** block EQUIPMENT_RENTAL lines; quote-level allocation from such a source is rejected when the quote contains any rental line — domain.py:20, funding.py:160-172
- §3.4 — insert — ambiguity — waterfall-created allocations are QUOTE_LEVEL, no quote_line_item_id, committed immediately — domain.py:300-313
- §3.4 — revise — mismatch — reversal guard reads on the funding source (any paid invoice naming that source blocks); reversal never un-exhausts an EXHAUSTED source — funding.py:215-228
- §3.5 — insert — ambiguity — job create accepts optional permit_status (default ISSUED if permit_number else NOT_REQUIRED); bad/non-clean permit status → ERR_INVALID_REQUEST 400; job_number format JOB-YYYYMMDD-NNN; inspection_required always true; progress_pct starts 0 — jobs.py:38-44, 55-76
- §3.5 — insert — ambiguity — self-pay coverage = SELF_PAY source APPROVED or EXHAUSTED with approved_cents ≥ quote total; self-pay-path scheduling leaves case status unchanged when not FUNDING_APPROVED — jobs.py:47-54, 81-82
- §3.5 — insert — ambiguity — job start early/wrong-state → ERR_INVALID_STATE_TRANSITION — jobs.py:120-125
- §3.5 — insert — ambiguity — completion request carries optional progress_pct (default 100) and unresolved-safety indicator; positive indicator → ERR_SAFETY_ITEMS_UNRESOLVED; progress≠100 → ERR_INVALID_REQUEST — jobs.py:155-176
- §3.5 — revise — ambiguity — job cancel reverses committed allocations attached to the job's quote — jobs.py:221-230
- §3.5 — insert — ambiguity — inspection create accepts optional correction_deadline; FINAL naming an uncompleted job → ERR_INSPECTION_BEFORE_COMPLETION; scheduling FINAL moves job inspection_status NOT_SCHEDULED→SCHEDULED — inspections.py:33, 41-45, 63-66
- §3.5 — revise — mismatch — safety-critical deficiency = code containing "SAFETY_CRITICAL"; pass merges request deficiencies before check; passed FINAL resolves job via installation_job_id or latest COMPLETED job; failed FINAL sets job inspection_status FAILED and reverts COMPLETED→IN_PROGRESS — inspections.py:94-125, 151-158
- §3.6 — revise — mismatch — `purchase_price_cents` is required at unit creation (was "if sold") — inventory.py:29
- §3.6 — insert — ambiguity — rental_end must be strictly after rental_start (ERR_INVALID_REQUEST); clinical guard reads latest completed assessment, proceeds when none; unit must be AVAILABLE else ERR_UNIT_UNAVAILABLE — rentals.py:85-109
- §3.6 — insert — ambiguity — month-count formula (year/month difference +1 when end.day > start.day, min 1); deposit's 20% cap rounded half up before comparison; last_billed_date initialized to rental_start — domain.py:138-152, rentals.py:124
- §3.6 — revise — ambiguity — deposit FORFEITED when confirm-pickup request flags forfeiture or reports condition POOR/DAMAGED/C/D, else REFUNDED — rentals.py:209-220
- §3.7 — insert — ambiguity — invoice_number format INV-YYYYMMDD-NNN — domain.py:349-351
- §3.7 — revise — mismatch — funding-cap guard re-evaluated whenever the invoice total is computed (creation always passes at total zero; enforced at line-add and send) — invoices.py:29-35, 86-87, 141, 162
- §3.7 — insert — ambiguity — sending an empty invoice → ERR_INVALID_REQUEST 400 — invoices.py:156-160
- §3.7 — revise — mismatch — no automatic monthly billing run exists; RENTAL_MONTHLY invoices are created manually; only automatic event is RENTAL_FINAL at pickup (DRAFT, single untaxed line, due +30d, skipped when unbilled period empty/zero) — rentals.py:24-72
- §3.8 — insert — ambiguity — claim_number format WC-YYYYMMDD-NNN; covered_by_warranty = reported on/before warranty_start + warranty_months (month-end clamped), false when no warranty start — claims.py:39-42, domain.py:221-225
- §3.8 — revise — mismatch — uncovered resolution generates DRAFT WARRANTY_WORK invoice (single untaxed line, due +30d) only when cost_cents positive; claim-close operation removed (no such endpoint); deny also stamps resolution_type DENIED; terminal states are RESOLVED and DENIED — claims.py:122-157, 161-172
- §3.8 — revise — mismatch — close guards: unpaid-invoice guard reads any non-VOID invoice with balance>0; guard failures and wrong-state close → ERR_INVALID_STATE_TRANSITION; terminal-case close/cancel → ERR_CASE_ALREADY_CLOSED — cases.py:119-141
- §3.8 — insert — ambiguity — cancel guard violations → ERR_INVALID_STATE_TRANSITION; cascade releases pending allocations of superseded quotes and withdrawn sources, leaves superseded_by_id null — cases.py:70-116
- §3.9 — revise — ambiguity — reassessment completion (REASSESSMENT/POST_INSTALL only) completes the earliest-due PENDING/SCHEDULED schedule, ties by creation order — assessments.py:178-187
- §5 — insert — ambiguity — added `ERR_NOT_FOUND` | 404 catalogue row — app.py:27-36
