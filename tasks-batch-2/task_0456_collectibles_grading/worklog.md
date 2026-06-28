# Worklog — task_0456_collectibles_grading

## Step 1: Create task directory — 2026-06-21T00:00:00.000Z

Created `tasks/task_0456_collectibles_grading/` and `tasks/task_0456_collectibles_grading/workspace/` (fixed directory, allocated by orchestrator; index-scan skipped). Difficulty target for Step 2: Expert (§0.4, 10–15 entities).

## Step 2: Generate scaffold — 2026-06-21T00:00:00.000Z

Generated the Expert-band scaffold for **Collectibles Grading & Authentication** at `tasks/task_0456_collectibles_grading/` (three files: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`).

**Lint verdict:** `clean lint` — all 401 §1.8/§1.9 calls conform to §1.5, all 14 FKs have reverse-reachability GETs.

**Entity count:** 14 (Expert band 10–15)
**Entities:** Customer, ServiceLevel, GradingStandard, Submission, SubmissionItem, IntakeRecord, GradeAssessment, AuthenticationCheck, Slab, Label, PopulationReport, InsurancePolicy, RegradeRequest, Shipment

**State machines:** 3 — SubmissionItem (cyclic crack-and-regrade loop: ENCAPSULATED→CRACK_PENDING→GRADING), Submission (compound posture derived from child item states), Shipment (linear with a LOST branch triggering an insurance payout). Plus 1 concurrency rule (OCC on SubmissionItem.version for regrade-create).

**Calculations:** 10 (provisional vs final grade, estimate vs final item fee, submission estimate/final aggregations, covered_value/premium, insurance_payout, population bump/decrement) — exhibits dual-variant logic on two distinct domains (grade vs fee) and pinned rounding orders (per-item-ceil-then-sum vs sum-then-ceil).

**Validation rules:** 15 (priority-ordered: auth → role → existence → ownership → state → OCC → safety → constraint → temporal → fiscal)
**Endpoints:** 49
**Error codes:** 19
**Roles:** 6 (Anonymous, Customer [entity_backed], Receiver/Grader/Authenticator/LabAdmin [opaque]) — peer_roles model

**§1.8 instances:** 18 (9 Difficulty Rules × 2 instances each)
**§1.9 instances:** 33 total (29 active + 4 `excluded_because` stubs) across all 9 claim-extraction sections

Key design choices: `api_prefix: ""` (flat-per-entity topology); all formula-derived asserts pinned to code-computed literals (grade 10/10/10/6 → provisional 9.0 / final 7.5; item over tier cap → estimate 6600 / final 6000; lost-shipment payout conserves store credit at covered value 50000/80000). Dead-end enum values (claim_status DENIED, RegradeRequest CANCELLED) removed for enum-closure compliance.

## Step 3: Copy INSTRUCTION.md — 2026-06-21T00:00:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_0456_collectibles_grading/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-06-21T00:00:00.000Z

**Output:** `workspace/PRD.md` — 288 lines.

**Major sections:** §1 Introduction; §2 Global Specifications (10 subsections: RBAC, response structure, pagination, common resource properties [Label flagged as `common_fields: false` exception], nested retrieval/existence ordering, validation ordering, monetary precision [integer cents, ceil insurance, floor grades], OCC on regrade, hierarchical posture/cascade, population census); §3 Business Logic (12 lifecycle-ordered subsections); §4 Endpoint Definitions (49 endpoints); §5 Error Code Catalogue (19 IDs).

**Hard Contracts — all PASS:** Contract 1 (field-name coverage, 0 missing after repair), Contract 2 (rule coverage: all transitions, 4 calc formulas in prose, all 19 errors, OCC `ERR_STALE_ITEM_VERSION`, enums, constants), Contract 3 (§3 path purity: 256 backtick tokens, 0 slash-prefixed/bare-method/method+path).

**Withheld files confirmation:** Did NOT read/grep/reference `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`. Worked only from `SCAFFOLD.yaml` + skill spec.

## Step 5: Generate unit tests — 2026-06-21T00:00:00.000Z

**Test files: 8** (1 conftest + 7 test modules) under `test_suite/`:
- `test_01_catalog_and_submission.py`, `test_02_grading_and_authentication.py`, `test_03_encapsulation_and_population.py`, `test_04_crack_and_regrade.py`, `test_05_insurance_and_shipment.py`, `test_06_intake_and_posture.py`, `test_07_access_and_validation.py`

**Total tests: 66** (each carries exactly one verbatim `Design:` tag).

**Provenance:** Queue A (§1.8 Difficulty): 18 instances → 36 tests (every instance ≥2 tests). Queue B (§1.9 Corner): 29 non-stub instances → 30 tests (every instance ≥1 test).

**Skipped instances:** None of the 47 non-stub instances skipped. The 4 corner `excluded_because:` stubs correctly NOT translated. One **assertion** dropped under unique-derivability: design's `version == 1` claim on submission-create — PRD §2.4 says version "begins at the resource's first persisted value" without pinning initial integer (0 vs 1 both faithful); sub-assertion omitted, common-field check relaxed to `version >= 0`.

**test_helpers/ files (9):** `__init__.py`, `types.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `factories.py`, `constants.py`, `test_users.py`, `fixtures.py`.

**Verification (all green):** every file compiles; all 90 quoted PRD citations survive literal grep of PRD.md; no orphan/dual/zero tags; no skip/xfail; no scaffold leakage; Customer threaded as only `entity_backed` role.

## Step 6: Generate implementation — 2026-06-21T00:00:00.000Z

Built complete Python + Flask REST API at `workspace/implementation/`.

**Source files (11 + launcher):** `start.sh`, `requirements.txt` (`Flask==3.0.3`), `app.py` (entry + error handlers + 50 routes), `db.py` (in-memory per-entity dicts + id/cert/timestamp/version helpers), `clock.py` (logical clock default `2026-01-01T00:00:00Z`), `response.py` (envelope), `errors.py` (`ApiError` + error-id→HTTP catalog), `middleware.py` (`X-User-ID`/`X-User-Role` auth + RBAC + pagination), `validation.py` (`ERR_INVALID_REQUEST` vs `ERR_VALIDATION`), `calculations.py` (Decimal grade floor-to-0.5, weighted/cap grades, ceil-insurance, fee/coverage/payout, census, title-key normalization), `serializers.py` (per-entity projections; Label = id+created_at only), `services.py` (posture re-derivation, cascades, recompute, population bump/decrement).

**Confirmations:** Python+Flask; in-memory dicts only (no SQLite/JSON/tmp/external, grep-verified; fresh boot = 0 entities, reset cert counter + clock); 50 endpoints; `start.sh` reads `$PORT` (default 10000), binds `0.0.0.0`, foreground via `exec`, guarded pip install; no startup seeding.

**Live smoke-test verified:** envelope + 3-digit ISO timestamps; auth/RBAC/ownership; existence-before-state; estimate (ceil-then-sum, uncapped) vs final fee (capped + `regrade_count*1500` surcharge); coverage premium (sum-then-ceil) recomputed on reject; provisional vs final grade cap; authentic-only boundary; population bump/decrement; full crack-and-regrade with OCC stale rejection (412); shipment loss cascade pays `covered_value` to store credit; duplicate-intake/counterfeit/alteration-note/subgrade-range/frozen/empty/declared-value/pagination all correct ids. One ordering fix during gen: duplicate-intake returns `ERR_DUPLICATE_INTAKE` before generic REGISTERED state guard (PRD §3.3).

## Step 7: Run tests and iterate — 2026-06-21T00:00:00.000Z

**Iterations run:** 2 (initial diagnosis sweep, then one fix batch validated by a full 8-round parallel sweep). Final state: all 8 parallel rounds pass 63/63 with zero flakiness. Starting state was a stable 54/66 (same 12 tests failed every round — no flakiness, all PRD-interpretation/fixture bugs).

### Tests deleted (3) — PRD-silence / unreachable-state per STEP 1b

- **`test_estimate_vs_final_fee_diverge_over_tier_cap`** (test_03) — UNREACHABLE SCENARIO. Needed an over-cap item (80000 > tier cap 50000) to survive submit and reach encapsulation, but PRD §3.2 verbatim rejects any over-cap item at submit with `ERR_DECLARED_VALUE_EXCEEDS_TIER`. The over-cap fee-divergence path of §3.8 is precluded by §3.2; no PRD-faithful impl can pass it. (Scaffold `dual_variant_calc/insurance_estimate_vs_final_fee_diverge_over_tier_cap`.)
- **`test_second_encapsulation_blocked_by_active_slab`** (test_03) — ERROR-PRECEDENCE / UNREACHABLE GUARD. Expected `ERR_ACTIVE_SLAB_EXISTS`, but after first encapsulation the item is `ENCAPSULATED` (not `AUTHENTICATED`), so the state check (§2.6 P5 `ERR_INVALID_STATE`) fires first. Active-slab guard is unreachable. (Scaffold `resource_temporal_overlap/single_active_slab_per_item_blocks_second_encapsulation`.)
- **`test_regrade_after_shipped_rejected`** (test_04) — ERROR-PRECEDENCE / UNREACHABLE GUARD. Expected `ERR_SUBMISSION_ALREADY_SHIPPED`, but §3.11 dispatch moves every covered item to `SHIPPED`, so the item is no longer `ENCAPSULATED` and the §3.7 state check (`ERR_INVALID_STATE`, ordered first) fires. Shipped guard unreachable. (Scaffold `state_machines/terminal_shipped_item_cannot_regrade`.)

### Fixes to `test_helpers/`

- **fixtures.py — `get_population_bucket`**: dropped the `title_key` query filter. PRD §3.10 gives `title_key` only by example and never pins the normalization algorithm (not uniquely derivable); helper was hardcoding raw title as key, never matching the impl's normalized key for multi-word titles. Now filters by `(grading_standard_id, grade_value)`, unique under per-test-server isolation. (Fixed 3 population tests in test_04.)
- **fixtures.py — `setup_multi_item_shipment_in_transit`**: reordered to log intake on all items before encapsulating any. PRD §3.3 permits intake only while submission is `SUBMITTED`/`RECEIVING`; per-item interleave advanced posture to `IN_GRADING` before the 2nd intake → `ERR_INVALID_STATE`. (Fixed 2 multi-item lost-payout tests.)

### Fixes to `test_suite/`

- **test_05** (4 lost-payout tests): changed over-cap declared values (80000 with cap 50000) to within-cap values producing identical asserted covered/payout numbers. PRD §3.2 forbids submitting over-cap items; cascade assertions (claim PAID, payout == covered, store_credit conservation) unaffected and remain faithful.
- **test_05 `test_shipment_create_allowed_once_submission_ready_to_ship`**: reordered inline loop to log all intakes before encapsulating (same §3.3 intake-window fix).
- **test_01 `test_delete_draft_item_decrements_count`**: replaced `validate_success(resp, expected_status=204)` (requires JSON envelope) with direct `resp.status_code == 204` check. PRD §4 mandates 204 No Content (no body) for item removal; envelope-requiring helper was a test mistranslation.

### Fixes to `implementation/`

**None.** Every implementation check was PRD-faithful; all 12 failures traced to non-derivable assertions (deleted) or fixture/test bugs (fixed in the test layers). Storage remains in-memory only; no PRD-untraceable capabilities added.

### Orchestrator verification note

Step 7's subagent reported the 8-round pass but the `results.{1..8}.json` artifacts had been cleaned. Orchestrator re-ran the 8-round sweep. **Methodology note:** an initial re-run used a bare `--start-command "bash start.sh"` (relying on cwd) which produced spurious 63/63 ERRORs — the per-test-server plugin (`pytest_plugin._parse_command`) only honors the working directory when the command has the `cd <dir> && ...` form; the bare form makes the per-test restart spawn from pytest's cwd, so the server never reboots and every test errors at setup. Re-running with the prescribed `cd .../workspace/implementation && bash start.sh` form confirmed **all 8 rounds pass 63/63, 0 failed, 0 errors**, with the canonical `results.{1..8}.json` artifacts written. Final suite size: 63 tests (66 − 3 deletions).

## Step 8: Finalize PRD — 2026-06-21T00:00:00.000Z

Skip condition NOT met (3 deletions + multiple test_helpers/test_suite fixes, though 0 implementation fixes) → Step 8 ran.

**Output:** `workspace/PRD_FINALIZED.md` — 287 lines (PRD.md = 287; delta 0 lines / +0.0%; single in-paragraph edit).

**Changes (1):**
- **§3.10 — revise — pinned the `title_key` normalization algorithm** (upper-case the title, extract maximal ASCII alphanumeric runs as tokens, drop all other characters as separators, join with single hyphens; stored on the bucket and matched against by the `title_key` query filter) — `implementation/calculations.py:130-135` (`normalize_title_key`).

**Per-edit pre-edit search log:** Subject = derivation of `PopulationReport.title_key` from `SubmissionItem.title` (PRD gave value only by example; field is serialized + queryable so behaviorally load-bearing). Enumerated paths: `calculations.normalize_title_key` (regex `[A-Za-z0-9]+`.upper joined by `-`); encapsulate bump (`app.py:742`) and crack decrement (`app.py:966`) both normalize identically (symmetric keys); `services.find_or_create_bucket`/`find_bucket` exact-string bucket identity; `list_population_reports` (`app.py:870-892`) exact-equality filter; `serializers.population_report`. Wording adjustment: described derivation from `title` (covers both callsites), added stored+queried clause so list-filter path isn't mis-described, used "ASCII letters and digits … every other character … dropped as separator" to capture `#57`→`57` without over-claiming non-ASCII handling.

**Deliberately NOT edited** (PRD already pins these; pure fixture/test bugs or unreachable-state deletions): 3 deleted tests (§3.2 over-cap rejection, §2.6 state-check-before-business-guard precedence), the §3.3 intake-window reorders, the test_01 204-No-Content check (§4 already mandates 204).

## Step 9: Complete PRD — 2026-06-21T00:00:00.000Z

Always-runs full PRD-vs-implementation scan, starting from `PRD_FINALIZED.md`.

**Output:** `workspace/PRD_COMPLETED.md` — 287 lines, 44992 chars (source `PRD_FINALIZED.md` = 287 lines / 43342 chars; **+1650 chars**, 11 lines revised in-paragraph, 0 lines added/removed).

**Counts:** 11 changes — **7 ambiguity-pins, 4 mismatch-revisions.**

**Per-change log:**
- §2.3 Pagination — insert — mismatch — intake/auth/per-slab-label/insurance-policy nested listings ignore `limit`/`offset`, return full set, report `limit`=10/`offset`=0 — `app.py:489,691,838,913`
- §2.4 Common Properties — revise — ambiguity — `version` begins at **1** — `db.py:51`
- §3.1 Service Levels — insert — ambiguity — duplicate `code` → `ERR_VALIDATION` — `app.py:116-117`
- §3.1 Grading Standards — insert — ambiguity — duplicate `code` → `ERR_VALIDATION`, before weight-normalization check — `app.py:180-185`
- §3.2 Submission building — insert — ambiguity — duplicate `email` → `ERR_VALIDATION` — `app.py:69-71`
- §3.3 Intake/reject — insert — ambiguity — reject on item whose intake `matches_declaration` is true → `ERR_INVALID_STATE` — `app.py:503-505`
- §3.4 Grading finalize — insert — ambiguity — finalizing unsuperseded assessment copies `final_overall` onto item `current_grade` — `app.py:634-637`
- §3.5 Authentication — revise — mismatch — `GENUINE` verdict always stores `alteration_note` null (supplied value discarded) — `app.py:666-667`
- §3.5 Label grade text — revise — mismatch — numeric `label_grade_text`: half-points keep ".5", whole grades drop fraction (10.0 → "10") — `calculations.py:123-127`
- §3.9 Insurance — insert — mismatch — `GET /submissions/{id}/insurance-policy` returns array envelope (`response_type` "array") with single policy — `app.py:906-915`
- §3.10 Population census — insert (2 clauses) — ambiguity — listing filterable by `grading_standard_id` + exact `grade_value`; `ALTERED`/"NOT GENUINE" slab counted in sentinel -1 bucket — `app.py:876-888`, `calculations.py:116-117`

**Deliberate non-changes:** `cert_number` format (`CERT0000000001`) left unpinned (PRD requires only uniqueness/non-reuse; exact string non-load-bearing); additive query filters on other generic list endpoints not documented (absence yields superset, not mismatch).

---

## Pipeline complete — 2026-06-21T00:00:00.000Z

All 9 steps done. Final state: **63/63 tests pass across all 8 parallel rounds, 0 failures, 0 errors** (verified by orchestrator with the canonical `cd .../implementation && bash start.sh` command form). Task directory contains SCAFFOLD.yaml + 2 design indices, worklog.md, test_helpers/ (9 files), test_suite/ (7 modules + conftest, 63 tests), and workspace/ with INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/ (12 source files + start.sh + results.{1..8}.json).
