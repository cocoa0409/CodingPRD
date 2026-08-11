# Worklog — task_0979_stairlift_mobility_equipment

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Task directory `tasks/task_0979_stairlift_mobility_equipment/` and its `workspace/` subdirectory pre-assigned and already present (per task specification; Step 1 auto-index scan skipped as instructed). Earlier headless attempt left no artifacts; pipeline restarts from Step 2.

## Step 2: Generate Scaffold — 2026-08-10T09:27:00.000Z

## Summary

Generated three scaffold artifacts under `/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/` from the verbatim scenario.

**Complexity profile**: primary archetype = workflow_orchestration, secondary = pricing_engine; layers = optimistic_concurrency + cascading_side_effects + dual_variant_calculation + scheduled_actions; hybrid topology; compound state-machine shape; approval_chain role model with segregation-of-duties elements (Assessor vs AssessmentReviewer); immediate consistency.

**SCAFFOLD.yaml** (`/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/SCAFFOLD.yaml`):
- 12 entities: Customer, HomeAssessment, ProductModel, EquipmentUnit, Quote, FundingApplication, Agreement, InstallJob, ServicePlan, WarrantyClaim, RemovalJob, AuditEvent
- 62 endpoints (incl. `/_clock/set_current_utc` with default 2026-05-01T00:00:00Z)
- 26 error codes, 9 roles (Customer is entity_backed; others opaque)
- 9 calculations (incl. dual-variant `provisional_quote_total`/`issued_quote_total`, `service_plan_fee` with waiver variant, `buyback_offer` with straight_line/market_adjusted variants, `funding_waterfall`, two distinct crew temporal-conflict rules with different interval semantics)
- 10 state machines (cyclic Quote revision loop; branching Agreement with mode-dependent removal gates; cascades on Assessment supersede and RemovalJob complete)
- 2 OCC concurrency rules (quote-accept on Customer.version, agreement-payment on Agreement.version)
- 14 ordered validation rows (auth → existence → state → safety → constraint → temporal → referential → fiscal)

**SCAFFOLD_DIFFICULTY_DESIGN.yaml**: 18 instances, exactly 2 per rule across all nine §0.5 rules; every instance has structured `setup_api_calls` + `trigger` + `assert` with literal numeric expectations (e.g., issued_total=636432 for CURVED PURCHASE; service_plan_fee 6370 vs 5415 standard/waiver; buyback straight_line=0 at month 120).

**SCAFFOLD_CORNER_DESIGN.yaml**: 27 instances across all nine guide sections — entities (6), state_machines (4), calculations (2), validations (5), endpoints (2), errors (3), roles (2), cross_cutting_complexity_layers (2), consistency_model (1).

**Design adjudications**:
- Buyback variant selected by Agreement.mode (RENTAL→straight_line, PURCHASE→market_adjusted) — pinned in calculation `variants`.
- Nested rounding order in `service_plan_fee` pinned: adders first, then 0.85 waiver discount, single final round_half_up.
- Funding waterfall priority ordering: `priority_rank ASC, created_at ASC` (never `id`), allocations capped per remaining balance; FUNDED transition triggers exactly when `funding_applied_cents >= list_price_cents`.
- Two crew temporal rules with intentionally different interval semantics (install = 60-min buffer on half-open intervals; removal = 2-per-UTC-day capacity), satisfying Rule 8's "different interval semantics on different resources" requirement.
- liability_waiver_signed exposed as an optional field on the quote-accept payload (rather than a separate PATCH) to keep the accept transactional.

**Lint verdict (verbatim)**:
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Coverage: 62 endpoints, 12 entities, 18 §1.8 instances, 27 §1.9 instances, 552 calls scanned.

## Step 3: Copy Shared Files — 2026-08-10T09:28:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0979_stairlift_mobility_equipment/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T09:39:00.000Z

## Summary

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/workspace/PRD.md` — a prose PRD for the stairlift/mobility-equipment sales & rental operations API, projected losslessly from `SCAFFOLD.yaml` (the difficulty/corner design files were not opened; no sibling task directories were touched).

**Section list:**
- §1 Introduction (2 paragraphs, pain-point + business-arc framing)
- §2 Global Specifications: 2.1 RBAC (9 roles, per-role `identity:` prose — `Customer` entity-backed, 8 opaque roles), 2.2 API Response Structure (verbatim fixed block), 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, four `meta` fields), 2.4 Logical Clock & Scheduled Sweeps (default `2026-05-01T00:00:00Z`, quote-expiry and plan-lapse sweeps, rental month accrual), 2.5 Resource Identity/Timestamps/Money (UUID `id`, 3-fraction-digit timestamps, `version`; `ProductModel`/`AuditEvent` explicitly carry only `id` + `created_at`; integer cents, round half-up), 2.6 OCC (both rules: `expected_customer_version` on quote accept, `expected_agreement_version` on payments, `ERR_STALE_VERSION`/412), 2.7 Crew Scheduling Discipline (60-min half-open install buffer with exact-adjacency exemption vs. 2-per-UTC-day removal capacity), 2.8 Pre-Request Check Ordering (all 14 validation priorities as an explicit ordered list), 2.9 Audit Trail
- §3 Business Logic (7 subsections, lifecycle-timeline grouping): 3.1 Intake & Assessment, 3.2 Catalogue & Inventory, 3.3 Quoting, 3.4 Acceptance/Funding/Payments, 3.5 Installation & Activation, 3.6 Service Plans & Warranty Claims, 3.7 Removal/Buyback/End-of-Life. All 9 calculations rendered as precise prose (rail-length Pythagoras, provisional vs. issued quote totals with pinned rounding order, funding waterfall with rank/created_at ordering, dual-variant buyback keyed on mode, waiver-discounted service-plan fee, outstanding rollup floored at 0, both crew rules)
- §4 Endpoint table — 62 rows, 4 columns only
- §5 Error catalogue — 26 rows, 2 columns only (all 25 scaffold errors + `ERR_INVALID_REQUEST`, which is in the scaffold catalog)

**Coverage audit result (mechanical):**
- Contract 1 Field-Name Coverage: 87 required identifiers (entity fields + endpoint inputs + query params + envelope fields), 87 present, 0 missing — PASS (two passes; pass 1 surfaced `quote_id`/`agreement_id` gaps, repaired in §3.4/§3.5 narrative)
- Contract 2 Rule Coverage: 14/14 validation priorities expressed in order; 2/2 OCC rejections fully specified; all transitions across 10 state machines expressed with preconditions + error ids + side effects; 9/9 calculations reconstructible; 62/62 endpoint side effects covered; sibling branches (restock/retire, 3 funding-decision branches, cancel from 3 states, dual buyback variants, waiver pricing variants) at equal density — PASS
- Contract 3 §3 Path Purity: 444 backtick tokens scanned, 0 path tokens, 0 bare-method tokens, 0 method+path tokens — PASS
- Endpoint table rows 62/62; error rows 26/26; role spellings 9/9; all state enum strings present

**Zero-Silence-Rule adjudications (scaffold ambiguities resolved conservatively, no invention):**
1. `QUOTE_TTL_DAYS` has no numeric value in the scaffold — PRD names it as a platform-configured constant without inventing a number.
2. `priority_rank` uniqueness within a quote has no nominated error id — PRD states the constraint but deliberately assigns no error code (rather than guessing `ERR_INVALID_REQUEST`).
3. Buyback formula references the removal's condition grade though `buyback_offered_cents` is computed at RemovalJob creation — PRD mirrors the scaffold wording ("grade recorded on the removal") without resolving the temporal paradox.
4. Install-completion price reconciliation: scaffold marks `measured_labor_hours`/"reconciliation variant" — PRD specifies recompute via the issued-price formula substituting actual `installed_rail_length_m` and `measured_labor_hours` for the pinned/catalog values.
5. `GET /product-models/{id}` — scaffold description says lookup is "by model_code"; PRD states the fetch resolves by `model_code`.
6. Funding decision sibling asymmetry preserved: `decision_reason` required for APPROVED and DENIED, not listed for PARTIALLY_APPROVED — mirrored deliberately.
7. Quote creation does not gate on assessment state (approval enforced at issue per the state machine); PRD adds no create-time gate.

## Step 5: Generate Unit Tests — 2026-08-10T10:05:00.000Z

# Generation summary — task_0979_stairlift_mobility_equipment

## test_helpers/ (Stage 1, 9 files)
- `/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/test_helpers/types.py` — 13 entity TypedDicts + 15 status/role enums; `ProductModel`/`AuditEvent` correctly omit `updated_at`/`version` (lean reference rows per PRD §2.5)
- `api_client.py` — `ApiClient(GenericApiClient)`, 66 methods covering every PRD endpoint under `/stairlift-ops`
- `api_errors.py` — all 26 `ApiErrorId` values + HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity shape assertions + agreement-money and coverage-cap invariant checkers
- `factories.py` — payload factories (input fields only)
- `constants.py` — PRD thresholds/pricing constants + standard catalog models and measurement sets (2400×3200 STRAIGHT→rail 4.00→issued 502000; 2800×3600 CURVED→rail 4.56→issued 636432)
- `test_users.py` — `TEST_USERS` for 8 opaque roles + `make_customer_headers(user_id)` for the entity-backed Customer role
- `fixtures.py` — 5-tier composite builders; OCC version tokens always re-read via fresh GET before guarded writes; **monotonic logical clock** (`set_clock` no-ops on non-forward moves) with per-scenario `timeline_offset_days` so multi-scenario tests (3-agreement crew-capacity) stay monotone; `create_refurbished_unit` runs a full sacrificial install→remove(REFURB_B)→restock lifecycle to produce a REFURB_B `IN_STOCK` unit (the fee-calculation instances require a REFURB_B installed unit, which plain receiving cannot produce)
- `__init__.py` — barrel export

## test_suite/ (Stage 2, 8 files, 59 tests)
- `conftest.py` + 7 test files: `test_01_registration_catalog_inventory_access.py` (11), `test_02_home_assessments.py` (6), `test_03_quotes.py` (12), `test_04_funding_and_agreements.py` (11), `test_05_install_jobs_and_crew_scheduling.py` (5), `test_06_service_plans_and_warranty_claims.py` (7), `test_07_removal_buyback_end_of_life.py` (7)

## Queue coverage
- **Queue A (Difficulty): 32 tests across 16 of 18 instances** (each covered instance has exactly 2 tests)
- **Queue B (Corner): 27 tests across all 27 non-stub instances** (no `excluded_because` stubs exist in this index)

## Skipped instances (PRD-first filter failures — gaps left as gaps)
1. **Difficulty/priority_pair_validation_conflict/business_temporal_vs_business_referential_on_install_create** — requires a FUNDED agreement whose reserved unit is simultaneously not RESERVED; no PRD endpoint sequence reaches that state (the unit flips back to IN_STOCK only via agreement cancel, which itself moves the agreement out of FUNDED and trips the earlier state gate). The dual-failure precondition is unreachable, so the priority-masked outcome is not PRD-derivable.
2. **Difficulty/boundary_precision_check/crew_overlap_zero_gap_boundary** — asserts a 60-minute gap is *allowed*, but the PRD's literal rule (both bookings extended ±60 min, half-open overlap test) makes [08:00,14:00) ∩ [13:00,17:00) non-empty at gap=60 → rejection. The asserted outcome contradicts the PRD-literal reading, failing unique derivability. (The PRD-unambiguous boundaries — 30-min rejection, exact-adjacency allowance, day-boundary capacity reset — are covered via `install_buffer_interval_semantics` and `removal_daily_capacity_semantics`.)

Other design-index defects corrected during faithful translation (asserted values preserved verbatim where PRD-derivable): A6 rental list price recomputed to the formula value (7500×24=180000 with partial pay 100000) since the recipe's 167000 was unreachable; `assessment_supersede_two_hop_cascade` translated per its own distinguishing aspect (MEASURED + DRAFT quote) because the PRD supersedes only SCHEDULED/MEASURED assessments, never APPROVED; OCC payments in recipes used stale-captured versions — fixtures re-read versions. One sanctioned relaxation: `expired_quote_accept_returns_quote_expired` uses `validate_error_is_one_of([ERR_QUOTE_EXPIRED, ERR_INVALID_STATE])` because the clock-set sweep moves ISSUED→EXPIRED before the accept, making the state gate (priority 4) vs freshness gate (priority 8) precedence ambiguous under §2.8.

## Stage 2 tag audit (automated sweep)
59/59 tests carry exactly one `Design:` tag on the final docstring line; 0 untagged, 0 dual-tagged, 0 unresolved tags; corner coverage 27/27; difficulty coverage 16/16 translated instances with ≥2 tests (2 instances skipped per above). Verbatim-citation sweep: ≥8-word probe from every test's quoted PRD citation greps literally against `workspace/PRD.md` — 0 failures. No `skip`/`skipif`/`xfail` markers anywhere. All modules compile and import cleanly.

## Step 6: Generate Implementation — 2026-08-10T10:05:00.000Z

## task_0979 stairlift_mobility_equipment — implementation generated

Generated a complete Python + Flask implementation under `/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/workspace/implementation/`.

### File list
- `start.sh` — foreground launcher, guarded `pip install` (skips when `flask` importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- `requirements.txt` — flask>=3.0
- `app.py` — Flask app factory, blueprint registration, ApiError/404/405/exception handlers
- `db.py` — in-memory stores (module-level dicts, all empty at boot; no seeding), logical clock defaulting to `2026-05-01T00:00:00Z`, `iso_z()` millisecond UTC formatting, UUID minting
- `errors.py` — `ApiError` + constructors for common error IDs
- `response.py` — envelope helpers: `{meta:{api_request_id, api_request_timestamp}, response_type, data}`, pagination fields `limit/offset/total_count/has_more` in `meta` for list responses only
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction and 9-role validation, `require_role`, JSON body + required-field checks, `limit`/`offset` parsing (default 10, min 1, max 100)
- `services/core.py` — `stamp_new` (id/created_at/updated_at/version=1), `stamp_lean` (ProductModel/AuditEvent: id+created_at only), `touch` (updated_at + version bump), `audit()`, customer outstanding rollup, ISO-8601 parsing
- `services/calculations.py` — all Table-3 rules with `Decimal`/`ROUND_HALF_UP`: `valid_rail_length` (Pythagoras, 2dp), `provisional_quote_total`, `issued_quote_total` (rail rounded first, then CURVED ×1.35 reround, then +45000 outdoor, +base, +labor), `funding_waterfall` (priority_rank ASC, created_at ASC tiebreak, capped at list price, auto-FUNDED), `buyback_offer` (RENTAL straight-line 120-month / PURCHASE market-adjusted 0.85^years × condition × region), `service_plan_fee` (tier base × (1+adders), waiver ×0.85 applied after adders), tier coverage matrix
- `services/sweeps.py` — `run_sweeps()` on clock set: ISSUED-quote expiry (expires_at <= now), ServicePlan lapse (agreement ACTIVE and next_service_due > 90 days past), rental month accrual per logical-month rollover; supersede-quotes cascade
- `routes/` — 12 blueprints: customers, home_assessments, product_models, equipment_units, quotes, funding, agreements, install_jobs, service_plans, warranty_claims, removal_jobs, misc (clock + audit-events)

### Endpoint count
62/62 registered — matches SCAFFOLD.yaml exactly (verified programmatically via `url_map`).

### Verification performed
Full lifecycle smoke tests on fresh boots: customer → assessment → measure → approve → quote → issue → accept (OCC) → funding waterfall auto-FUNDED → install job (crew buffer + too-early) → complete cascades (unit INSTALLED, customer ACTIVE, quote reconciliation hook) → service plan (waiver fee 5623 verified) → activate → payment OCC → removal (rental balance gate, daily capacity) → removal-complete cascade (claims DENIED/AGREEMENT_REMOVED, plan CANCELLED, unit REMOVED+graded) → close → customer FORMER → restock. Error paths verified: ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_UNAUTHORIZED, ERR_INVALID_STATE, ERR_INVALID_MEASUREMENT (range + curved geometry), ERR_STAIR_TOO_NARROW, ERR_MODEL_INCOMPATIBLE, ERR_STALE_VERSION (412 both OCC endpoints), ERR_WAIVER_BLOCKS_CLAIM, ERR_RENTAL_BALANCE_OUTSTANDING, ERR_CREW_OVERLAP, ERR_INSTALL_ALREADY_SCHEDULED, ERR_TOO_EARLY, quote expiry sweep, assessment supersede cascade (MEASURED → SUPERSEDED pulls DRAFT/ISSUED quotes along), pagination meta.

### Design decisions where PRD/scaffold was ambiguous
1. **InstallJob create after FAILED**: scaffold transition says create requires FUNDED, but PRD §3.5 says a failed job leaves the agreement SCHEDULED and "a fresh install job may be created." Implemented per PRD: create accepts FUNDED or SCHEDULED; the FUNDED→SCHEDULED status write only fires from FUNDED. This also makes ERR_INSTALL_ALREADY_SCHEDULED reachable per the priority-8 ordering.
2. **Buyback grade at creation time**: `buyback_offered_cents` is computed at RemovalJob creation but `condition_grade_at_removal` is only supplied at completion. Used the unit's current condition grade (NEW → treated as REFURB_A) as the assessor-estimate baseline, since the PRD pins the computation to job creation.
3. **`_activated_at`/`_installed_at`/`_rental_months_accrued`**: internal underscore-prefixed fields on Agreement to drive cooling-off, rental accrual, and buyback month math; never part of the public schema but returned in serialization (harmless, additive).
4. **Quote TTL**: `QUOTE_TTL_DAYS` is named as a platform constant but never given a value in PRD/scaffold; set to 30 days.
5. **Decimal exponents**: `0.85 ** years` computed via `Decimal.__pow__` with float-free path (Decimal power of Decimal) — adequate precision for cent-level rounding at the tested magnitudes.

## Step 7: Run Tests and Iterate — 2026-08-10T10:25:00.000Z

**Summary — task_0979_stairlift_mobility_equipment**

- **Iterations run**: 3 sweeps of the 8-round parallel stability sweep. Sweep 1: 22 deterministic failures (8/8 rounds each). Sweep 2: all assertions passed in all rounds, but rounds 4 and 7 each had one test error in setup from the runner's "API server could not be restarted" guard — a load-induced harness flake at the lockstep test_07 tail (8 rounds × 8 cores), not a test or implementation defect. Sweep 3 (after boot-latency mitigation): fully clean, 8 rounds × 59/59 passed.

- **Tests deleted**: none.

- **Fixes applied to `test_helpers/`**:
  - `constants.py` — `MEASURE_CURVED` changed from rise 2800 / run 3600 to rise 2000 / run 4100. The old pair violated PRD §3.1 verbatim ("for `CURVED`, the `stair_run_mm` must be at least twice the `stair_rise_mm`"), so the PRD-faithful implementation correctly rejected the fixture with `ERR_INVALID_MEASUREMENT`. The new pair satisfies the geometry gate (4100 ≥ 4000) while preserving rail = 4.56 m (sqrt(2.0²+4.1²) = 4.5618 → 4.56), so every dependent expected value (issued total 636432, install rail 4.56) is unchanged.
  - `fixtures.py` — added `reset_clock_cache()`. The module-level `_clock_state` monotonic guard persisted across tests in the pytest process while `per-test-server` isolation reboots the server (logical clock back to 2026-05-01) before every test; a test running after one that advanced the clock far forward (e.g. test_03's expiry test sets 2026-08-15) saw its `set_clock` calls no-op, leaving the fresh server at boot time → `ERR_TOO_EARLY` cascades across 19 tests in test_04/05/06/07.

- **Fixes applied to `test_suite/`**:
  - `conftest.py` — added an autouse fixture calling `reset_clock_cache()` before every test, matching the per-test server reboot lifecycle.
  - `test_03_quotes.py` — docstring/comment updates only (rise 2000 / run 4100), no assertion changes.

- **Fixes applied to `implementation/`**:
  - `routes/agreements.py` `cancel_agreement` — now moves **every** funding application on the quote to `WITHDRAWN` (previously only `PENDING` ones), per PRD §3.4 verbatim: "every funding application on the quote moves to `WITHDRAWN`". Fixes `test_cancel_from_funded_withdraws_applications_and_releases_unit` (APPROVED app must become WITHDRAWN).
  - `start.sh` + `app.py` — single-interpreter boot: the guarded flask install moved into `app.py` as an ImportError fallback, eliminating the extra `python3 -c "import flask"` process per boot (472 boots per sweep under 8× parallel load on a saturated 8-core host; the runner's restart poll window is ~15 s and two boots exceeded it in sweep 2).

Final state: 8/8 rounds, 59/59 tests passed, 0 failed, 0 errors.

## Step 8: Finalize PRD — 2026-08-10T10:27:00.000Z

**Done.** `PRD_FINALIZED.md` is in place at `/home/ubuntu/github/CodingPRD/tasks/task_0979_stairlift_mobility_equipment/workspace/PRD_FINALIZED.md` — and the correct minimal patch is **zero edits**: it is byte-identical to `PRD.md`.

**Why no edits:** every `<step_7_diff>` item traces to a case where the PRD already uniquely determines the behavior, or to a change with no PRD surface:

1. **`constants.py` MEASURE_CURVED fixture (rise 2800/run 3600 → 2000/4100)** — pure fixture bug. The old pair violated PRD §3.1's verbatim rule ("for `CURVED`, the `stair_run_mm` must be at least twice the `stair_rise_mm`"); the implementation (`implementation/routes/home_assessments.py:114-117`) correctly enforced the PRD. PRD was already right.
2. **`fixtures.py` `reset_clock_cache()` + `conftest.py` autouse fixture** — test-harness lifecycle bug (module-level monotonic cache surviving per-test server reboots). Implementation clock behavior (`implementation/db.py:10-11` default `2026-05-01T00:00:00Z`; `implementation/routes/misc.py:15-25` admin-only set + sweeps) matches PRD §2.4 verbatim.
3. **`test_03_quotes.py` docstring updates** — comment-only, no behavior.
4. **`routes/agreements.py` `cancel_agreement` withdraw-all** — an implementation bug fixed *toward* the PRD, which already says verbatim in §3.4: "every funding application on the quote moves to `WITHDRAWN`". The fixed code (agreements.py:147-151) matches that sentence exactly.
5. **`start.sh` + `app.py` single-interpreter boot** — harness-level boot change, no API behavior.

**Summary on exit (for worklog.md):**

- PRD.md vs PRD_FINALIZED.md: 298 lines vs 298 lines, 0.0% delta (identical files).
- Changes: none — every step_7_diff item was either a fixture bug violating an already-correct PRD, an implementation bug fixed to match the PRD's existing verbatim wording, or a harness/boot change with no PRD surface.
- Per-edit pre-edit search log: no edits committed. One candidate edit was evaluated and rejected:
  - (a) Subject: whether cancel-agreement's withdrawal of *all* funding applications (not just `PENDING`) needed PRD pinning.
  - (b) Impl paths enumerated: `implementation/routes/agreements.py:60-78` (skip_funding `DENIED`/`WITHDRAWN` gate) and `implementation/routes/agreements.py:129-157` (cancel_agreement: install-job cancel cascade, unit release to `IN_STOCK`, withdraw-all loop at lines 147-151, agreement → `CANCELLED`, rollup recompute); a repo-wide grep for `WITHDRAWN` across `implementation/**/*.py` confirmed these are the only two sites touching that status.
  - (c) Wording adjustment: none needed — PRD §3.4's existing sentence "every funding application on the quote moves to `WITHDRAWN`" already uniquely describes the fixed implementation; any edit would be pure churn and risk a new mismatch.

Note: `test_helpers/` and `test_suite/` are not present in this workspace (only `INSTRUCTION.md`, `PRD.md`, `implementation/`), so verification of fixture-side items relied on the step_7_diff narrative cross-checked against the implementation, which is the alignment target.

## Step 9: Complete PRD — 2026-08-10T10:31:00.000Z

## Exit summary

**Source vs. completed:** PRD_FINALIZED.md 298 lines / 47,706 chars → PRD_COMPLETED.md 298 lines / 48,631 chars (+925 chars, +0 lines).

**Counts:** ambiguity-pins: 6; mismatch-revisions: 4.

**Changes (one bullet each):**
- §2.3 Pagination — insert — ambiguity — pinned that negative `offset`, non-integer `limit`/`offset`, and out-of-range `limit` are all `ERR_INVALID_REQUEST` (400) — implementation/middleware.py:53-65
- §3.3 Quoting (issue) — insert — ambiguity — pinned `QUOTE_TTL_DAYS` to 30 days — implementation/services/sweeps.py:8, implementation/routes/quotes.py:161
- §3.3 Quoting (revise/accept freshness) — revise — mismatch — changed "expires_at has already passed" to "has been reached or passed" (impl rejects at `expires_at <= now`, equality included) — implementation/routes/quotes.py:175,220
- §3.4 Funding decisions — revise — mismatch — PRD said only denials require `decision_reason`; impl requires a non-empty `decision_reason` string on every decision, and denial zeroes `approved_cents` — implementation/routes/funding.py:97-98,120-121
- §3.5 Install job create — revise — mismatch — PRD required agreement `FUNDED` only; impl accepts `FUNDED` or `SCHEDULED` (post-`FAILED` recreation), already-`SCHEDULED` agreements remain so — implementation/routes/install_jobs.py:53-56,92-94
- §3.5 Activation — insert — ambiguity — pinned internal bookkeeping fields `_activated_at`, `_installed_at`, `_rental_months_accrued` recorded on the agreement and present in its serialization — implementation/routes/agreements.py:117-118, implementation/routes/install_jobs.py:167
- §3.6 Claim filing — insert — ambiguity — pinned that the named `service_plan_id` must resolve but is not required to belong to the agreement — implementation/routes/warranty_claims.py:43-45
- §3.7 Buyback offer — insert — ambiguity — pinned that at RemovalJob creation the unit's current `condition_grade` stands in for the not-yet-recorded removal grade, with `NEW` treated as `REFURB_A` — implementation/routes/removal_jobs.py:82-87
- §4 Endpoint table (List Customers) — insert — ambiguity — pinned the `Customer` role as excluded from the customer list endpoint (impl's role gate excludes it) — implementation/routes/customers.py:38-39
- §4 Endpoint table (Create Quote) — revise — mismatch — description said "measured/approved assessment"; impl checks only assessment existence (state gate applies at issue, per §3.3), so changed to "an existing assessment" — implementation/routes/quotes.py:46-48

**Verified but already pinned (no change needed):** Decimal `0.85**years` market-adjusted math (calculations.py:125-127), funding-waterfall ordering/cap, skip-funding waiver-or-all-denied rule, cooling-off measured from install completion, claim-adjudication fiscal gates and approved=min(claimed, headroom), service-plan fee adders/waiver discount, OCC scopes, lean-vs-common entity field sets, and both crew-scheduling rules all matched PRD prose as written.

**Deliberately not pinned:** 405→404 normalization and the catch-all 500→400 handler in app.py (outside PRD's stated scope of the 4xx error format).
