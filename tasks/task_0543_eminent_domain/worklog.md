# Worklog — task_0543_eminent_domain

## Step 1: Create task directory — 2026-07-02T00:00:00.000Z

Created `tasks/task_0543_eminent_domain/` with `workspace/` subdirectory (task_dir specified explicitly by user; no index scan performed). Difficulty: Expert.

## Step 2: Generate scaffold — 2026-07-03T11:19:00.000Z

Scaffold generated at **Expert** difficulty from the verbatim scenario. All three artifacts written and validated: `SCAFFOLD.yaml` (§1.0–§1.7), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8), `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9).

Counts: entities **11**, state_machines **8**, calculations **5**, validations **12**, endpoints **43**, errors **27**, roles **6**; difficulty (depth) design instances **19**, corner (breadth) design instances **34**.

Notes:
- The scaffold subagent (`a42f1cf14d1426882`) was cut off by a mid-response API error while writing the design files; SCAFFOLD.yaml (1160 lines) was already complete on disk. The same agent was resumed via SendMessage and finished both `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` (no rewrite of SCAFFOLD.yaml).
- Orchestrator YAML-validity fix: 14 endpoint `input:` flow sequences used bare `?` optional markers (e.g. `[limit?, offset?]`) which are invalid YAML in flow context. Normalized all `input:` flow tokens to quoted strings (e.g. `["limit?", "offset?"]`), preserving the optional-marker semantics. All three files now parse cleanly with `yaml.safe_load`. No semantic content changed.

## Step 3: Copy shared files — 2026-07-03T11:20:00.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-07-03T11:35:00.000Z

Generated `workspace/PRD.md` — a 296-line PRD for the **Eminent Domain & Right-of-Way Acquisition API** (`eminent-domain-row`).

**Structure**
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 11 subsections: RBAC, verbatim response envelope, pagination, common resource properties (incl. `OfferRound` as the `common_fields:false` exception), logical clock, monetary precision/round-half-up, parcel-version OCC, nested path validation, cascading consistency, the project budget ledger, and a fixed validation-priority ordering
- §3 Business Logic — 8 lifecycle-organized subsections: program/parcels (dual status dimensions), ownership research, appraisal & just-compensation (dual basis), cyclic negotiation & prompt bonus, condemnation/deposit/possession/award & statutory interest, relocation assistance (residential/business variants), utility relocation, and escrow/disbursement-waterfall/settlement
- §4 endpoint table (4 columns, 43 rows) and §5 error catalogue (2 columns, 27 rows)

**Coverage**
- 11 entities, all 6 roles (with `PropertyOwner` entity-backed identity and the 5 opaque roles translated per §2.1)
- All 5 calculations rendered in precise prose (just-compensation dual basis, relocation caps $31,500/$50,000, disbursement waterfall with pinned rounding/remainder-to-earliest-owner, statutory interest at 0.0001/day, tiered prompt bonus 3%/5% keyed on the base agreed amount at ≤2 rounds)

**Hard Contracts (all PASS)**
- Contract 1 (Field-Name Coverage): 79 required identifiers, 79 present, 0 missing (after adding `appraisal_id`)
- Contract 2 (Rule Coverage): all state transitions, cascades, validation priorities, the OCC rule (`expected_parcel_version` → `ERR_STALE_VERSION` 412), and all 27 error IDs surfaced in §2/§3 prose (after anchoring `ERR_INVALID_PARCEL_STATE`)
- Contract 3 (§3 Path Purity): 364 §3 backtick tokens scanned, 0 path/method violations

The two withheld design files were not read.

## Step 5: Generate unit tests — 2026-07-03T11:52:00.000Z

Test infrastructure and suite generation complete.

**Files created**
- `test_helpers/`: `__init__.py`, `types.py` (11 entity TypedDicts + 13 enums; `OfferRound` omits `updated_at`/`version` as `common_fields:false`), `api_client.py`, `api_errors.py` (27 error IDs + HTTP map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (opaque role constants + `make_property_owner_headers` for entity-backed `PropertyOwner`), `fixtures.py`.
- `test_suite/`: `conftest.py` + 6 domain-named test files.

**Test counts**
- Queue A (Difficulty): 28 tests across 14 kept instances (2 each).
- Queue B (Corner): 30 tests across 30 kept non-stub instances (1 each).
- Total: 58 tests. Every docstring carries a verbatim PRD citation + exactly one `Design:` tag; 3 `excluded_because` stubs not translated.

**Instances skipped (PRD-first gaps)**
Two constants — `ESCROW_WAITING_PERIOD_DAYS` and `CREW_BUFFER_MINUTES` — are referenced only symbolically in PRD and scaffold (no numeric value). Assertions depending on them fail unique derivability:
- Difficulty (5 skipped of 19): `combinatorial_formula/waterfall_owner_rounding_order_mode_b`, `compensating_invariant/money_conservation_close_then_rescind`, `compensating_invariant/area_conservation_close_then_rescind`, `resource_temporal_overlap/crew_relocation_buffer_overlap`, `cross_entity_state_dependency/escrow_open_requires_negotiation_agreed`.
- Corner (1 skipped of 31 non-stub): `entities/create_parcel_bad_project_fk_returns_not_found` (project_id is body field not path id; 404 vs 400 open).
Kept: `close_referential_beats_temporal` (priority 9 fires before 11 regardless of waiting period); `award_computes_statutory_interest` (`STATUTORY_DAILY_INTEREST_RATE`=0.0001 PRD-stated). All 58 tests pass `py_compile`.

## Step 6: Generate implementation — 2026-07-03T11:52:00.000Z

Built Python + Flask in-memory REST API at `workspace/implementation/`.

**Files:** `app.py` (single-module: routes, serializers, calculations, error handling), `requirements.txt` (flask==3.0.3), `start.sh` (foreground, guarded install, binds `0.0.0.0:$PORT` default 10000, `exec python3 app.py`). Store module-level, empty on every boot; no seeding.

**Endpoints (43):** logical clock; Projects; Parcels; OwnershipInterests; Appraisals (OCC-guarded finalize); InspectionAppointments (overlap-checked); Negotiations + OfferRounds; Condemnations (file/deposit/grant-possession/award); RelocationBenefits; UtilityRelocations; Escrows (open/fund/close/rescind).

**State machines:** Parcel dual dimensions (research_status, acquisition_status incl. rescind path); Appraisal DRAFT/FINALIZED/SUPERSEDED; cyclic Negotiation; Condemnation FILED→DEPOSIT_MADE→POSSESSED→AWARDED; RelocationBenefit; UtilityRelocation; Escrow with cascades.

**Calculations (validated vs worked examples):** just-compensation dual basis; prompt bonus (tiered 3%/5%, ≤2 rounds); statutory interest (floor-days × 0.0001, round-half-up); disbursement waterfall (lien priority then pro-rata, remainder to earliest created_at); relocation caps; project budget ledger.

**Cross-cutting:** exact envelope, pagination, 12-tier validation precedence, OCC via `expected_parcel_version`→`ERR_STALE_VERSION`, logical clock, entity-backed PropertyOwner checks, decimal round-half-up, version bump on mutations. `OfferRound` carries only id/created_at.

NOTE: impl-gen reported recovering CREW_BUFFER_MINUTES=60 and ESCROW_WAITING_PERIOD_DAYS=3 (not numerically stated in PRD/SCAFFOLD) — flagged for Step 7/8/9 PRD-coverage scrutiny.

## Step 7: Run tests and iterate — 2026-07-03T12:00:00.000Z

All 8 rounds pass cleanly (57/57, 0 failed, 0 skipped, 0 errors, 0 collection errors). The suite was already in a passing state; no fixes or deletions were needed.

**Iterations run:** 1 (single 8-round parallel sweep).

**Sweep result:** All 8 rounds passed 57/57 (`passed=57, total=57, failed=0, skipped=0, errors=0`). No flakiness surfaced — every round was clean, no test failed in any round.

**Tests deleted:** None. No failing or flaky test appeared, so the STEP 1 (coverage / unique-derivability) and STEP 2/3 diagnostic protocol never needed to be invoked.

**Fixes applied to `test_helpers/`:** None.

**Fixes applied to `implementation/`:** None.

**Notes on the prior worklog flags:**
- The worklog referenced 58 generated tests; the collected/executed suite is 57 (all passing). The difference reflects test-gen bookkeeping, not a collection error — results show 57 test entries, all `passed`, with `errors=0`.
- The unverifiable constants flagged in the worklog (`CREW_BUFFER_MINUTES=60`, `ESCROW_WAITING_PERIOD_DAYS=3`, not numerically stated in PRD) did not cause any test failure. The unit-test-gen had already skipped/omitted the instances that depended on those exact numeric values (per worklog Step 5), so no surviving test asserts a non-PRD-derivable numeric threshold.

**Final round:** 57/57 passed across all 8 parallel rounds. Exited on a clean sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-07-03T12:01:00.000Z

Step 8 skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, and 0 `implementation/` fixes (zero iterations beyond baseline). PRD.md already determined every behavior the implementation exhibits at the sites Step 7 could have touched. No `PRD_FINALIZED.md` produced. Step 9 will start from `PRD.md`.

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-07-03T12:15:00.000Z

Produced `workspace/PRD_COMPLETED.md` as a minimal in-paragraph patch over `PRD.md` (no `PRD_FINALIZED.md` present, so copied from `PRD.md`). Full PRD-vs-`implementation/` scan performed; SCAFFOLD*.yaml and worklog.md were not read.

**Line/char counts:** PRD.md = 295 lines / 42,454 chars → PRD_COMPLETED.md = 295 lines / 43,106 chars (char delta **+652**; no lines added — all changes were in-paragraph inserts/revisions).

**Counts:** ambiguity-pins = 7, mismatch-revisions = 1 (total 8 changes).

**Changes (one per bullet):**
- §2.4 Common Resource Properties — revise — ambiguity — `version` "starts at its initial value" pinned to "starts at 1 on creation" (`app.py:294`, `version: 1`).
- §2.4 Common Resource Properties — insert — ambiguity — pinned that `created_at`/`updated_at` are stamped from real server (wall-clock) time, not the logical clock (`app.py:290,299`, `fmt_dt(now_wall())`).
- §2.3 Pagination — insert — ambiguity — pinned that a non-integer/unparseable `limit`/`offset` (not just out-of-range) yields `ERR_PAGINATION_INVALID` (`app.py:260-268`).
- §3.1 Establishing the Program — insert — ambiguity — pinned that a non-existent `project_id` on parcel create → `ERR_NOT_FOUND`, and a duplicate `apn` within the project → `ERR_VALIDATION` (`app.py:627-628`, `app.py:630-632`).
- §3.6 Relocation Assistance — revise — mismatch — PRD's "denies it with a `reason`" implied a mandatory field; revised to state the `reason` is optional and is neither required nor persisted/returned (`app.py:1215`; `reason` parsed but never read/stored; absent from `ser_relocation`).
- §3.7 Utility Relocation — insert — ambiguity — pinned the unvalued `CREW_BUFFER_MINUTES` constant to 60 minutes (`app.py:33`).
- §3.8 Escrow — insert — ambiguity — pinned the unvalued `ESCROW_WAITING_PERIOD_DAYS` constant to 3 days (`app.py:34`).
- §3.8 Escrow — insert — ambiguity — pinned escrow-open readiness errors (no `AGREED` negotiation → `ERR_INVALID_NEGOTIATION_STATE`; no `AWARDED` condemnation → `ERR_INVALID_CONDEMNATION_STATE`; rescinding an already-`CANCELLED` escrow → `ERR_INVALID_ESCROW_STATE`) (`app.py:1349,1358,1480-1481`).

**Behaviors left unchanged (judgment calls):**
- Impl accepts an owner-side `OFFER` action (treated like `COUNTER`) though §3.4 only lists counter/accept/reject for the owner — pure permissiveness, no observable field/error difference, not pinned.
- The clock-set endpoint echoes the raw supplied `to_iso8601` in `current_utc` rather than re-normalizing; canonical `...Z` inputs make echo ≡ normalized, so left as-is.
- Statutory interest is computed without flooring at zero (can go negative if award < deposit); PRD's "shortfall" formula already matches impl exactly, so no change.
