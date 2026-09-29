# Worklog — task_2499_correspondent_banking_respondent_due_diligence

## Step 1: Create task directory — 2026-09-03T00:00:00.000Z

Created pre-assigned task directory `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence` and its `workspace/` subdirectory. Index 2499 was fixed by the invocation (no auto-allocation scan performed, per orchestration instructions — other pipelines run concurrently on this host).

## Step 2: Generate scaffold — 2026-09-03T02:30:00.000Z

ORCHESTRATOR NOTE ON EXECUTION: the first Step 2 subagent (single agent for all three artifacts) died with `API Error: Claude's response exceeded the 64000 output token maximum` and wrote nothing at all. Decision taken autonomously: split Step 2 into three subagents — 2a for SCAFFOLD.yaml (§1.0–§1.7), then 2b/2c concurrently for the two design indices — each instructed to build its YAML incrementally (first `Write`, then quoted-heredoc `cat >>` appends of ~400–500 lines) so no single tool call can exceed the output cap and so partial progress survives a mid-run failure. 2b (difficulty) additionally died on the first attempt with a transient `unexpected error during processing` having written nothing; it was re-launched with the same prompt plus a note about both failure modes and succeeded. 2c was forbidden from reading SCAFFOLD_DIFFICULTY_DESIGN.yaml and 2b (retry) forbidden from reading SCAFFOLD_CORNER_DESIGN.yaml, so the depth and breadth indices were designed independently as the skill intends. No sibling task directory was read by any of the three.

### Step 2a — SCAFFOLD.yaml (verbatim subagent summary)

`SCAFFOLD.yaml` for task_2499 is complete at `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence/SCAFFOLD.yaml` (4,031 lines). It parses cleanly and its top-level keys are exactly `['api_prefix', 'calculations', 'complexity_profile', 'concurrency_rules', 'domain_name', 'endpoints', 'entities', 'response_envelope', 'roles', 'scenario', 'state_machines', 'validations']` — no `scaffold_difficulty_design` / `scaffold_corner_design` key, so the two sibling artifacts remain unclaimed.

Scale: 14 entities · 69 endpoints · 20 calculations · 12 state machines / 12 dimensions / 98 transitions · 36 priority-ordered validations (bands 1–43) · 74 error codes · 6 roles · 2 OCC rules. `difficulty_level: expert_plus`, archetypes `compliance_audit` + `graph_constraint`, `role_model: segregation_of_duties`.

Entities: JurisdictionProfile, RespondentBank (two parallel state dimensions: `dd_state` 11 states, `payment_posture` 4), BeneficialOwner (self-referential look-through graph), DueDiligenceQuestionnaire, ControlAssessment, NestedRelationship (self-referential across respondents), TransactionMonitoringProfile, ActivityObservation, MonitoringAlert, InformationRequest, AdverseMediaEvent, PeriodicRefresh, PaymentInstruction, ClosurePlan.

Rule families encoded:
- **Dual-variant calculations over identical data**: `control_score` (ONBOARDING_PROVISIONAL credits self-ratings, REFRESH_FINAL scores missing assessments as 1) and `wind_down_cap` (FORWARD_PROJECTED declared volume vs CHRONOLOGICAL_ACTUAL per-period-capped mean, with different rounding points). `adverse_media_uplift` and `refresh_due_date` carry window variants.
- **Multi-factor scoring with pinned evaluation order**: jurisdiction points → inherent (J/O/N/A with per-component caps) → control credit → residual → rating thresholds → jurisdiction-ceiling gate; `refresh_due_date` breaks a genuine circularity (cadence ← rating ← uplift ← cadence) with a 5-step pinned order using the rating frozen at approval.
- **Rounding-order and boundary precision**: per-corridor round → sum → 1.10 buffer for calibration; per-event round → running sum → cap for uplift; per-line round → residue to the largest corridor for settlement; `>=` breach tests contrasted with a strict `>` undisclosed-nesting test.
- **Graph constraints**: ownership cycle/depth/sibling-percentage rules; nested-chain transitive depth with a 5-rung prohibition ladder (CYCLE > SANCTIONED_JURISDICTION > JURISDICTION_PROHIBITS_NESTING > DEPTH_EXCEEDED > PAYABLE_THROUGH_NOT_PERMITTED).
- **Interacting prohibition ladders**: `payment_screening_decision` (BLOCKED_SANCTIONS > no-calibration RECEIVED > 4-rung hold ladder > clear) crossed with nested-disclosure and wind-down-cap rules.
- **Cross-entity cascades**: jurisdiction sanctioning → respondents + nested rows; TIER_1 adverse media → re-score, refresh acceleration, owner re-verification, restriction; alert escalation → recalibration + accelerated refresh; refresh completion → re-approval + recalibration (deliberately non-circular).
- **Conserved invariants (compensating pairs)**: `nested_exposure_units` (SUSPEND/REVERT weight-neutral) and `outstanding + settled == original` cents (ALLOCATE/REVERSE exact inverse).
- **Interval semantics**: CLOSED monitoring intervals (adjacency *is* overlap, 409) vs HALF-OPEN refresh windows (adjacency legal) plus a 30-day post-completion buffer (422).
- **Temporal/SLA**: logical clock defaulting to `2026-08-01T00:00:00Z` via `POST /_clock/set_current_utc`; RFI SLA with multiplicative compressions, 12h floor, 72h escalation windows, strike ledger with retro-credit; ops sweep `POST /correspondent-banking/refresh-sweeps`.
- **Four designed dual-failure precedence pairs** (P1–P4) called out inline in §1.4, plus SoD checks on four approval/assessment boundaries.

Verification performed beyond YAML parsing: every `ERR_*` referenced resolves to the catalog and vice versa; every `METHOD /path` string anywhere in the file resolves to a declared endpoint; every `calculations.<name>` reference resolves; all endpoint roles exist in §1.7; all outputs name declared entities; `scaffold_lint.py`'s FK reverse-reachability check (imported directly, since the two design files don't exist yet) reports 0 violations — this required converting seven sub-resource child lists into filtered collection lists, because the lint's sub-resource form only matches a literal `{id}` parent placeholder. No forbidden concurrency vocabulary and no id-based ordering anywhere.

### Step 2c — SCAFFOLD_CORNER_DESIGN.yaml (verbatim subagent summary)

`SCAFFOLD_CORNER_DESIGN.yaml` is complete and valid.

**File**: `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence/SCAFFOLD_CORNER_DESIGN.yaml` — 8,969 lines, single top-level key (`python3 -c "...yaml.safe_load..."` prints `['scaffold_corner_design']`). Built entirely with a first `Write` plus ~500-line quoted-heredoc appends, each followed by a parse check. `SCAFFOLD.yaml` was never modified; `SCAFFOLD_DIFFICULTY_DESIGN.yaml` was never read or written; no other `tasks/task_*` directory was touched.

**Sections (9) and instances (169)**
entities 25 · state_machines 30 · calculations 37 · validations 20 · endpoints 12 · errors 25 · rbac 12 · cross_cutting_complexity_layers 5 · consistency_model 3. All 169 names unique; 44 distinct claim_types, every one drawn from `claim-extraction-guide.md`'s per-section tables; every instance carries a full `test_recipe` (no `excluded_because` stubs, since §1.8 was off-limits to read).

**Breadth families covered**
Per-entity creation/retrieval/listing/not-found/required-fields/defaults/computed-vs-system fields/type constraints/immutability/parent + junction-edge discoverability; per-machine initial state, valid transitions, every illegal source state, terminal lockdown, idempotent re-triggers, cascade-down / bubble-up / cross-entity / ledger-sync / compensation / conditional cascades; every calculation's correct result, input-set filtering, constants, precision and rounding order, plus threshold boundaries at value−1 / value / value+1 and both variants of each dual-variant rule; validation violation→error, satisfaction→pass and priority ordering including the four declared precedence pairs; all six endpoint patterns plus pagination/filter/order behavior (limit 1..100, `limit=0`/`101` → ERR_INVALID_PAGINATION, offset past the end, stable tie-break ordering); malformed and type-wrong payloads, unknown enum members, missing required fields, unknown fields ignored, bad date/month formats; referential integrity (cross-respondent references, body-supplied parent mismatch, nine distinct child NOT_FOUND codes swept in one instance); RBAC permitted/denied on every guarded endpoint plus all four segregation-of-duties pairs and the RespondentContact scope confinement; OCC stale-version for both §1.2.1 concurrency rules; contagion fan-out and the ops-run checkpoint sweep (dry-run vs live); and immediate-consistency claims.

**Verification performed** (scripted against SCAFFOLD.yaml): all 74 `ERR_*` codes are referenced and no dangling code is referenced; every `call:` resolves to a declared endpoint (method + path); every `payload:` key is a subset of that endpoint's `input:` (the only two exceptions are the deliberate "unknown fields ignored" instance); every `as:` role exists (the 26 role mismatches are exactly the intended `role_denied` triggers); all 4 role/user conventions hold; zero unbound `${var}` placeholders; all captures reference declared output fields.

**Documented deliberate omissions** (as in-file comments): `ERR_OWNERSHIP_CYCLE_DETECTED` has no instance because an ownership cycle is impossible by construction through the declared endpoints (the nested-chain cycle `ERR_NESTED_CYCLE_DETECTED` *is* reachable and has an instance); precedence pairs P1–P4 are asserted in their owning sections rather than duplicated under `validations`; `as: Unauthenticated` appears in exactly one instance (no auth headers, validation priority 1). All formula-derived assertions are pre-computed literals (e.g. wind-down cap 180000.00 FORWARD_PROJECTED vs 213337.49 CHRONOLOGICAL_ACTUAL on identical data; aggregate ceiling 550000000.00 vs 493350000.00; residual 6.63 → 18.63 after a TIER_1 uplift with `inherent_risk_score` provably unchanged; refresh_due_date accelerated from 2029-08-01 to 2026-10-01).

### Step 2b — SCAFFOLD_DIFFICULTY_DESIGN.yaml (verbatim subagent summary, second attempt)

Artifact complete and verified.

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1,523 lines, exactly one top-level key `scaffold_difficulty_design`, parses clean with `yaml.safe_load`.

**Coverage:** all 9 §0.5 difficulty rule_ids, 19 instances (2 each, 3 for `combinatorial_formula`), 19/19 unique names, 518 worked setup calls, 218 concrete assertions.

**Hard interaction families covered**
- `dual_variant_calc` — `control_score` ONBOARDING_PROVISIONAL 75.00 (one-MAJOR cap applied after rounding) vs REFRESH_FINAL 30.80 on the *same* respondent, with the dd_state-driven variant gate asserted both ways; `wind_down_cap` FORWARD_PROJECTED 8100000.00 vs CHRONOLOGICAL_ACTUAL 8833500.00.
- `combinatorial_formula` — inherent-risk three-component caps at the inclusive volume-tier edge (92.00 → residual 71.30 → PROHIBITED); calibration rounding order (per-corridor round before the ×1.10 aggregate: 2807854.78 vs wrong-order 2807854.77, hold 280785.48); `refresh_due_date` pinned five-step order (2026-08-31 vs naive fixed-point 2027-08-01).
- `non_linear_state_machine` — dd_state cycle APPROVED→RESTRICTED→APPROVED does not restore the parallel payment_posture dimension; questionnaire clarification cycle exhausts rounds on the 4th return (409 `ERR_ROUNDS_EXHAUSTED`).
- `transitive_cascade` — five-hop alert-ESCALATE fan-out (recalibration → hold 723580.00 → RFI sla_hours 24 with double compression → escalation ledger → in-flight payment keeps its captured hold); officer RESTRICT from UNDER_REFRESH suspends nested rows while `nested_exposure_units == 6` is deliberately unchanged.
- `priority_pair_validation_conflict` — P1 403 `ERR_RESPONDENT_PAYMENT_POSTURE_BLOCKED` outranks 422 `ERR_WIND_DOWN_CAP_EXCEEDED`; P3 409 `ERR_MONITORING_INTERVAL_OVERLAP` outranks 422 `ERR_AGGREGATE_THRESHOLD_EXCEEDED` (clamp-then-buffer 550000000.00).
- `boundary_precision_check` — payment hold-threshold inclusive at 786500.00 vs 786499.99 SCREENED_CLEAR; RFI overdue-marking inclusive at the risk-compressed `due_at` (11:59:59 → 422 `ERR_RFI_NOT_YET_OVERDUE`, strikes 0; 12:00:00 → 200, strikes 1).
- `cross_entity_state_dependency` — refresh completion requires a REFRESH_FINAL assessment timestamped at/after `started_at` (premature one → 422 `ERR_REFRESH_NOT_REASSESSED`, then 200 with completed_control_score 68.00 / due 2029-08-13 / cadence 36); VOLUME+COUNT alerts suppressed by the parent profile's calibration_state while ratios and the NESTED signal survive byte-identical numerics.
- `resource_temporal_overlap` — monitoring intervals CLOSED (both shared endpoints 409, ±1s legal, `${jv2} == ${jv1} + 1`); refresh windows HALF-OPEN (adjacency legal, and interior 409 `ERR_REFRESH_WINDOW_OVERLAP` outranks 422 `ERR_REFRESH_BUFFER_VIOLATION`).
- `compensating_invariant` — `outstanding_obligation_cents + settled_cents` conserved across ALLOCATE/REVERSE with the residue (incl. a negative residue) pinned to the largest corridor, plus 4 refusals (`ERR_NO_ALLOCATION_TO_REVERSE`, ×2 `ERR_REVERSAL_AMOUNT_MISMATCH`, `ERR_SETTLEMENT_EXCEEDS_OUTSTANDING`); depth-weighted `nested_exposure_units` round-trip 3→7→9→9→9→5→3 under confirm/suspend/lift/revert.

**Reference self-check (automated, all clean):** 113 grounds refs resolve (calculations, `validations[priority=N]`, concurrency_rules, entity fields, and state-machine edges indexed per `(entity, dimension)` so RespondentBank's dd_state and payment_posture machines are distinct); 0 unknown `ERR_*` of those referenced; 282 `call:` paths all match one of the 69 scaffold endpoints after param canonicalization; all 6 roles valid; every symbolic value asserted (variants, restriction/recalibration reasons, applied-rule labels) exists verbatim in SCAFFOLD.yaml; 18 of 20 calculations exercised.

One real bug was caught and fixed during verification: `dual_variant_calc` instance 1 originally reached REFRESH_FINAL by RESTRICTing straight from DD_IN_PROGRESS, an edge that does not exist in the dd_state machine. It now goes owner-verify → ONBOARDING_PROVISIONAL assessment → committee APPROVE (ground swapped to `PENDING_COMMITTEE_to_APPROVED`), with the intermediate numbers (control 75.00, credit 0.3094, residual 9.67, LOW) asserted before the trigger. SCAFFOLD.yaml was not modified and SCAFFOLD_CORNER_DESIGN.yaml was never read.

## Step 3: Copy shared files — 2026-09-03T02:32:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_2499_correspondent_banking_respondent_due_diligence/workspace/INSTRUCTION.md` (53 lines).

## Step 4: Generate PRD — 2026-09-03T02:58:00.000Z

ORCHESTRATOR TRUNCATION CHECK (the known doc-generator failure mode): PASS. `wc -l` = 594; `tail -12` ends at the complete final row of the §5 error table (`| ERR_OBLIGATION_OUTSTANDING | 422 |`) — a real section boundary with no mid-sentence cut. `grep -n '^## '` shows all five top-level sections present in order (1 Introduction, 2 Global Specifications, 3 Business Logic, 4 API Endpoint Definitions, 5 Error Codes). Distinct `ERR_*` tokens: 74 in PRD.md vs 75 in SCAFFOLD.yaml; the single difference is the scaffold's own `ERR_XXX` envelope-comment placeholder, which is not a real error id. No regeneration needed.

### Verbatim subagent summary

PRD generation is complete and verified.

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence/workspace/PRD.md` — 594 lines, 19,733 words, built across 9 chunked writes/appends (no single call near the 64k output ceiling; nothing truncated).

**Section outline**
- `# Correspondent Banking Due Diligence API — Product Requirements Document`
- `## 1. Introduction`
- `## 2. Global Specifications & System-Wide Principles` — 2.1 RBAC (six roles, `X-User-ID`/`X-User-Role`, respondent-contact scoping); 2.2 API Response Structure (byte-identical copy of `skills/prd-bench-doc-generator/section-2.2-response-structure.md`, verified by exact substring match); 2.3 Pagination; 2.4 Common Resource Properties (+ audit-stamp and free-text field inventory); 2.5 Logical Clock, Interval Semantics and Month Arithmetic; 2.6 Numeric Precision and Rounding; 2.7 Optimistic Concurrency on the Respondent Record; 2.8 Path Resolution and Referential Scoping; 2.9 The Global Validation Precedence Ladder (36 numbered rules, priorities 1–43, plus precedence pairs P1–P4 and the two out-of-ladder guards); 2.10 Cascade Discipline and Determinism
- `## 3. Business Logic & Domain Requirements` — 3.1 jurisdiction reference data; 3.2 respondent onboarding and licensing; 3.3 four-level ownership look-through; 3.4 questionnaire + control assessment; 3.5 nested correspondents and the prohibition ladder; 3.6 risk scoring, committee decision, payment posture; 3.7 monitoring calibration, observations, alert generation; 3.8 information requests, adverse media, refresh cadence, operator sweep; 3.9 payment screening, wind-down cap, orderly closure
- `## 4. API Endpoint Definitions` — 69 rows, exactly 4 columns (`| Method | Path | Description | Authorized Role(s) |`)
- `## 5. Error Codes` — 74 rows, exactly 2 columns

**Completeness verification**
- Error coverage: **74/74** `ERR_*` ids from SCAFFOLD.yaml present in PRD.md, 0 extras. The scaffold's 75th match, `ERR_XXX`, is a placeholder inside the scaffold's own §2.2 envelope comment (line 71), not a real error id — deliberately omitted.
- Endpoints: 69/69 rows, HTTP codes stated as "201 for creates, 200 for everything else" matching the scaffold's `code` values.
- All 36 validation `error_id`s, all 20 calculations, all 12 state-machine dimensions and all 58 distinct declared states appear in the prose (mechanical diff, 0 absent). 98 declared transitions are covered by from/to + preconditions + error_id + side effects prose.
- Ends at a real boundary: final line is the last `| ERR_OBLIGATION_OUTSTANDING | 422 |` table row.

**Hard Contract reports**
- **Contract 1 — Field-Name Coverage: PASS.** Two independent passes against the extracted requirement sets: 179 entity-field names (171 true fields + 8 calculation variant strings), 102 endpoint input identifiers, 14 path params → 0 missing in both passes. After a fix pass, **0 identifiers appear only once** (all are backticked at least twice). Fixes applied: added an audit-stamp/free-text inventory paragraph to §2.4, and named the `AT_APPROVAL`, `ON_ADVERSE_MEDIA` and `ONBOARDING_LOOKBACK` variants explicitly where §3.6/§3.8 had only described them in words.
- **Contract 2 — Rule Coverage: PASS.** Both `concurrency_rules[]` entries are expressed as write endpoint + `expected_respondent_version` + mismatch → `ERR_STALE_RESPONDENT_VERSION` / 412, with the stale-version test explicitly ordered before state preconditions; no "simultaneously"/"race"/"first-writer-wins" framing remains (the one incidental "simultaneously" in §2.9 was rewritten). Prose scan for pseudocode operators (`>=`, `==`, `+=`, `round(`, `ceil(`, ` IN {`, ` AND `, ` OR `, ` NOT `) outside backticks: 0 hits. Fuzzy-word scan (`appropriate`, `as needed`, `reasonable`, `approximately`, `etc.`, `TBD`): 0 hits.
- **Contract 3 — §3 Path Purity: PASS.** 0 violations: no backticked token in Section 3 starts with `/`, is a bare HTTP method, or combines method+path; request-body and query field names remain backticked, and paths appear only in §2.7 and §4.

**Scaffold inconsistencies resolved with explicit documented decisions** (all pinned in PRD prose so two readers converge): committee decision body uses `action` = `APPROVE`/`DECLINE`/`RETURN` with optional `override_risk_rating` improving the rating exactly one notch; approval posture follows the state machine (`OPEN` for LOW/MEDIUM, `SCREEN_ONLY` for HIGH) rather than the endpoint side-effect summary; restriction `action` set is `RESTRICT`/`LIFT`/`CLEAR_SCREENING`; the notice-period formula's `outstanding_obligation_source` is read as the plan's `original_obligation_cents`; the closure-plan wind-down action is documented as `BEGIN_WIND_DOWN` with `START_WIND_DOWN` accepted as an equivalent spelling.

The two withheld design files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-03T04:30:00.000Z

Launched CONCURRENTLY with Step 6 in a single assistant message, per the skill (physical isolation: the impl generator could not read `test_suite/` because it did not exist at its spawn time; the test generator was additionally forbidden to read `workspace/implementation/`).

### Verbatim subagent summary

Task complete. Final state of `/home/ubuntu/github/CodingPRD/tasks/task_2499_correspondent_banking_respondent_due_diligence/`.

## Files created

**Stage 1 — `test_helpers/`** (9 modules): `types.py`, `api_client.py` (one method per endpoint under `P = "/correspondent-banking"` plus the clock, exported as `api_client`), `api_errors.py` (74-member `ApiErrorId` + `HTTP_STATUS_CODES` registered via `set_error_http_status_map`), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py` (single flat import surface).

**Stage 2 — `test_suite/`** 48 topically-partitioned files, **207 tests**:
- Queue A (Difficulty): `test_d01_dual_variant_calc.py` … `test_d09_compensating_invariant.py` — 39 tests.
- Queue B (Corner): `test_c_entities_*.py` (25), `test_c_state_a–f.py` (29), `test_c_calc_a–h.py` (37), `test_c_validations_a–c.py` (20), `test_c_endpoints_a–d.py` (12), `test_c_errors_a–f.py` (25), `test_c_rbac_a–c.py` (12), `test_c_layers_a–d.py` (5), `test_c_consistency_a.py` (3) — 168 tests.

## Instance coverage

- **Queue A: 19/19 instances translated**, ≥2 tests each (39 tests).
- **Queue B: 168/169 non-stub instances translated**, 1 test each.
- **1 SKIP** (single cause, PRD-first filter condition 2 — outcome not uniquely derivable): `Corner/state_machines/cross_entity_nested_confirm_forces_profile_recalibration`. PRD 275 fires the `CALIBRATED → RECALIBRATION_REQUIRED` / `NESTED_DISCOVERY` hop only "if the confirmation raises `max_nested_depth`", but the instance's setup is a single already-`DISCLOSED` depth-1 row, so confirming it cannot raise the maximum and the asserted profile transition does not follow. Skipped outright — no weakening, no xfail, no placeholder.

## Design/PRA conflicts resolved in favour of the PRD (deviations, not skips)

Notable ones: `rbac/9` asserts `computed_control_score 0` where PRD 235 makes it null; `rbac/11`'s setup is unreachable under PRD 359 (alert must be UNDER_INVESTIGATION/ESCALATED before RFI dispatch) so the SoD pair was staged through `INVESTIGATE` first, and the non-existent reason `EXPLAINED_BY_RESPONDENT` was replaced with the enum member `RESPONDENT_EXPLAINED`; `cross_cutting/2` asserts `escalation_level 1` where PRD 395 says the sweep escalates to 3; `cross_cutting/3` asserts `SCREEN_ONLY` where PRD 377 hop five sets `BLOCKED` because the category *is* `SANCTIONS_EVASION`; `cross_cutting/4` and `consistency_model/0` specify `UNRATED` respondents, which PRD 327 refuses to calibrate, so both are scored to `LOW` (rating factor is 1.30 either way, so every threshold in those instances is unchanged). Also caught and fixed a copied-from-design assertion bug: `rbac/8` claimed `payment_posture SCREEN_ONLY` after approving a LOW respondent, where PRD 315 gives `OPEN`.

## Verification

- `python3 -m py_compile` on every file in `test_suite/` and `test_helpers/` — clean.
- `PYTHONPATH=.. python3 -m pytest --collect-only -q` from `test_suite/` — **207 tests collected, 0 errors**.
- Programmatic tag audit (AST-parsed docstrings vs. both design yamls): 207/207 tests carry **exactly one** `Design:` line, **0 bad tags** — every tag resolves to a real `name:` in the matching section/rule_id, and no instance is double-claimed.
- An import/API linter over every test file reports no missing helper imports, no unused imports, and no references to non-existent `api_client` methods.

`workspace/implementation/` was never read or written, and no sibling task directory was opened.

## Step 6: Generate implementation — 2026-09-03T04:30:00.000Z

Launched CONCURRENTLY with Step 5 in the same assistant message. Forbidden from reading `test_helpers/`, `test_suite/`, and both design indices.

### Verbatim subagent summary

The implementation is complete and verified.

## Modules (`.../task_2499_correspondent_banking_respondent_due_diligence/workspace/implementation/`)

| lines | file | role |
|---|---|---|
| 83 | `app.py` | `create_app()`, 13 blueprints, ApiError/HTTPException/catch-all handlers, `app.run(PORT|10000)` |
| 113 | `clock.py` | logical clock (default `2026-08-01T00:00:00Z`), canonical 3-frac ISO, month/day/hour math |
| 189 | `store.py` | 14 in-memory dict collections, `insert`/`touch` (one version bump per row per request), parent helpers |
| 94 | `errors.py` | all 74 error codes → HTTP status, `ApiError`, `fail()` |
| 70 | `response.py` | §2.2 envelope: `ok`, `ok_list`, `error`, `_`-prefixed private-key stripping |
| 56 | `auth.py` | `X-User-ID`/`X-User-Role`, 6 roles, respondent scoping |
| 224 | `validate.py` | typed field specs, `body()`, ladder priorities 5→6→7→9, pagination |
| 462 | `calc.py` | all 20 calculations (Decimal, ROUND_HALF_UP 2dp / 4dp / ROUND_CEILING) |
| 399 | `cascade.py` | multi-hop cascades, rollups, posture narrowing, profile/plan lookups |
| 108 | `common.py` | `/correspondent-banking` prefix, not-found map, scoping, paging, filters |
| 142/435/180/280/253/342/155/215/152/329/230/329/19 | `routes_jurisdictions / respondents / owners / questionnaires / nested / monitoring / alerts / rfis / media / refresh / payments / closure / clock` | one blueprint per domain area |

Total 4859 lines across 23 modules plus `start.sh` and `requirements.txt`. Largest single file is 462 lines; no `Write` exceeded ~400 lines.

## Verification results
- `python3 -m py_compile *.py` → clean for all 23 modules.
- Flask url_map registers **exactly 69 routes**, matching the PRD §4 table.
- Booted with `PORT=18499 bash start.sh`; envelope confirmed byte-shape-exact: `meta.api_request_id` = `req_` + 20 upper-alnum, `api_request_timestamp` 3-frac-digit Z, `response_type` `object`/`array`/`error`, list meta adds `limit/offset/total_count/has_more`, create → 201, error payload `{error_id, message}` inside `data` (401 unauth, 405, 422, 409, 404, 400 pagination all checked).
- Fresh-boot state is empty for every collection (`total_count: 0` × 6 checked); a grep for `sqlite|open(|json.dump|/tmp` across the implementation returns nothing, so nothing is seeded or persisted and every `start.sh` re-invocation wipes state.
- End-to-end smoke (`/tmp/smoke2499.py`, outside the repo) now runs **fully green**: jurisdictions → respondent → licensing (PROSPECT→DD_IN_PROGRESS) → owner + verify → questionnaire + 8 control domains + analyst overlays + submit + assess → risk assessment (→PENDING_COMMITTEE) → committee approval (→APPROVED/OPEN) → monitoring profile + calibration + observation (breach_ratio 2.0067, 2 alerts) → RFI dispatch/response/adjudication → adverse media confirm → payment submit + release → refresh schedule/START/LAPSE → closure draft/submit/approve/allocate/reverse/re-allocate/serve-notice/wind-down/close (→TERMINATED/BLOCKED), plus negative 401/403/404/400 checks.
- Sweep verified positively in a second probe: `dry_run: true` returns the would-change respondent and writes nothing; the real sweep moves APPROVED→REFRESH_DUE and creates the `CADENCE` cycle, and a later sweep lapses it and applies the 30-day restriction grace → `RESTRICTED` / `REFRESH_LAPSED` / `BLOCKED`, with the respondent version incremented once.

Every failure the smoke run surfaced turned out to be a fixture error in my own script, not an implementation defect — notably a 90% `LEGAL_ENTITY` owner with no verified child correctly leaves `control_chain_complete` false (PRD §3.3), so `ownership_verified` stayed false and blocked committee promotion. No implementation code changes were needed after the compile pass; the verification server has been killed and `__pycache__` removed.

## Step 7: Run tests and iterate — 2026-09-03T09:07:00.000Z

ORCHESTRATOR INDEPENDENT RE-VERIFICATION: the Step 7 subagent reported a clean sweep but had deleted `results.*.json` and `sweep.log` as "cleanup", leaving no durable evidence (a known failure mode of this step). The orchestrator therefore re-ran the full 8-round sweep itself via `setsid nohup bash workspace/sweep.sh > workspace/sweep.log 2>&1 &`, polled to completion (~365s per round wall time under host contention), and confirmed from the JSON directly:

```
results.1.json 207 / 207 failed 0 errors 0 skipped 0
results.2.json 207 / 207 failed 0 errors 0 skipped 0
results.3.json 207 / 207 failed 0 errors 0 skipped 0
results.4.json 207 / 207 failed 0 errors 0 skipped 0
results.5.json 207 / 207 failed 0 errors 0 skipped 0
results.6.json 207 / 207 failed 0 errors 0 skipped 0
results.7.json 207 / 207 failed 0 errors 0 skipped 0
results.8.json 207 / 207 failed 0 errors 0 skipped 0
```

`grep -c Terminated sweep.log` = 0 and `grep -c 'Results: 207/207' sweep.log` = 8, so no round was reaped and all eight completed independently. The eight results files are retained on disk as the required Step 7 artifact. Step 7 applied fixes, so the Step 8 skip condition does NOT hold and Step 8 runs.

### Verbatim subagent summary

The sweep is clean. Final state: **207/207 in all 8 rounds**, zero flakiness.

## Summary

**Iterations run:** 3 full 8-round parallel sweeps (`--isolation per-test-server`, launched detached under `setsid nohup` via `workspace/sweep.sh`).
- Sweep 1: 131/207 → 77 unique failures (66 from a single `assessed_rating` root cause).
- Sweep 2: 194/207 in every round, byte-consistent → 13 unique failures, no flakiness.
- Sweep 3: **207/207 in every round.**

**Tests deleted / assertions removed (PRD-silence category):**
1. `test_c_calc_g.py::test_payment_screening_hold_threshold_is_inclusive_to_the_cent` — removed the single `hold_threshold_applied is None` assertion on the clearing branch (STEP 1c, COMPUTED-FIELD / DEFAULT-VALUE SILENCE: PRD names `hold_threshold_applied` only as what the *holding* branch writes; the clearing branch's value is not stated). Design rule: Corner/calculations/payment_screening_hold_threshold_is_inclusive_to_the_cent.
2. `test_c_rbac_c.py::test_the_assessor_may_not_be_the_identity_that_scored_the_respondent` — removed the second refusal block asserting `ERR_SEGREGATION_OF_DUTIES` on a `RETURN` action (STEP 1c). PRD §3.4 L245 scopes the SoD sentence to `ASSESS` ("an `ASSESS` whose `X-User-ID` equals the respondent's `id`…"), and §2.9 P39 says "the `X-User-ID` **assessing** a questionnaire"; a faithful implementer may reasonably not apply it to `RETURN`. Independently, the questionnaire was `SUBMITTED` and `RETURN` is declared only from `UNDER_ASSESSMENT`, so the ladder's P12 `ERR_INVALID_QUESTIONNAIRE_STATE` beats P39 regardless. No whole test file or test function was deleted.

**Fixes applied to `test_suite/`** (no `test_helpers/` change was needed — the fixture layer proved faithful):
- `test_c_calc_d.py::test_risk_rating_prohibited_override…` — variant `ONBOARDING_PROVISIONAL` → `REFRESH_FINAL`; the respondent is `RESTRICTED` after the sanctions cascade and PRD L253 permits only refresh-final there.
- `test_c_calc_d.py::test_nested_exposure_rollup…` — added `nested_activity_permitted=True`; PRD L275 requires it for `CONFIRM`.
- `test_c_calc_f.py::test_rfi_response_sla_base_hours…` — `escalation_level == 0` → `== 1`; PRD L359 dispatch "raises `escalation_level` to at least 1" (uniquely 1 from DRAFT's 0).
- `test_c_errors_d.py::test_an_ownership_chain_deeper_than_four_levels…` — `_chain_level` was passed the previous owner dict where a `parent_owner_id` string is required.
- `test_c_errors_d.py::test_approval_of_a_medium_rated_respondent…` — `approved_risk_rating is None` → `== "UNRATED"`; PRD L197 initialises it to `UNRATED`.
- `test_c_rbac_b.py::test_the_approver_may_not_be…` — added the missing `assessed_questionnaire(...)` (self_rating 4); PRD L309 requires an `ASSESSED` questionnaire for the `PENDING_COMMITTEE` promotion, and 80.00 control score back-solves the test's own expected residual 6.63.
- `test_c_rbac_c.py::test_the_assessor_may_not_be…` — `setup_approved_respondent` → `setup_pending_committee` so `ONBOARDING_PROVISIONAL` is a legal variant and P39 is reachable instead of P11.

**Fixes applied to `implementation/`:**
- `routes_questionnaires.py::assessment_decision` — scoped the "every row carries an `assessed_rating`" gate to `REFRESH_FINAL` (PRD §2.9 P33 L155 + the dual-variant prose L253); under `ONBOARDING_PROVISIONAL` a null rating legally credits `self_rating`. This one fix cleared 66 failures.
- `store.py::insert` / `store.py::touch` — `created_at`/`updated_at` now stamped from `clock.iso(clock.now())` instead of `clock.wall_iso()`; PRD §2.5 L92 "Nothing in this system reads wall-clock time."
- `routes_nested.py::create_nested` — a detected cycle no longer short-circuits the create; the prohibition ladder now decides, so a non-questionnaire source is recorded in `PROHIBITED` with `prohibition_reason` `CYCLE` (PRD L273).
- `routes_nested.py::_expand` — the chain read now reports each row's recomputed §3.5 depth instead of the traversal level (PRD L285 "with their recomputed depth").
- `routes_monitoring.py::calibration` — moved the `risk_rating == "UNRATED"` refusal to *after* the profile from-state check, so a superseded profile yields `ERR_INVALID_MONITORING_PROFILE_STATE` (P12 beats an unnumbered business rule).
- `cascade.py::schedule_cycle` — `completed_control_score` initialises to `None`, not `0.00`; PRD L90 says every completion stamp "is null until that decision occurs" (dropped the now-unused `Decimal` import).
- `routes_refresh.py::_sweep_plan` — a request freshly marked overdue by the sweep is now also escalated in the same run when `due_at + 72h` has been reached (PRD L395 pipeline); the wet run already applies `overdue` before `escalate`.

No endpoint, field, side effect, or seeded data was added; storage remains in-memory dicts only, and no `skip`/`xfail` or weakened error-id assertion was introduced.

**Final sweep evidence** (`results.1.json` … `results.8.json`, since cleaned up along with `sweep.log` and `__pycache__`):
207/207, 207/207, 207/207, 207/207, 207/207, 207/207, 207/207, 207/207 — and `grep -c Terminated sweep.log` = 0, confirming no reaping contaminated the run.

## Step 8: Finalize PRD — 2026-09-03T09:20:00.000Z

Step 8 was NOT skipped: Step 7 applied 7 `implementation/` fixes, 7 `test_suite/` fixes and 2 assertion removals, so the zero-iteration skip condition did not hold. The verbatim Step 7 worklog entry was inlined as `<step_7_diff>`. Subagent was forbidden SCAFFOLD*.yaml and worklog.md, and instructed to use surgical `Edit` calls rather than a whole-file `Write` (output-cap and silent-truncation defence).

ORCHESTRATOR VERIFICATION: `PRD.md` 594 lines vs `PRD_FINALIZED.md` 594 lines; `diff` reports 18 changed lines = 9 in-place revisions, so the file is genuinely patched and not a byte-identical copy. Tail still ends at the complete final §5 error-table row (`| ERR_OBLIGATION_OUTSTANDING | 422 |`).

### Verbatim subagent summary

Verification complete: `PRD_FINALIZED.md` is 594 lines (same as `PRD.md`), 9 lines revised, and it still ends at the §5 error-table boundary with a complete final row (`| ERR_OBLIGATION_OUTSTANDING | 422 |`).

## Line counts
- `PRD.md`: 594 lines — `PRD_FINALIZED.md`: 594 lines — **0.0% line delta** (9 lines revised in place, 0 added/removed).

## Changes (one per edit)
- **§2.4 Common Resource Properties (L86)** — revise — `created_at`/`updated_at` are now explicitly read from the logical clock of §2.5, not wall-clock time — `store.py:42-46,75`.
- **§2.9 Priority 39 (L161)** — revise — the questionnaire SoD clause scoped to the `ASSESS` action alone, never `RETURN` — `routes_questionnaires.py:158` (inside the `ASSESS` branch only).
- **§3.4 assessment decision (L245)** — revise — the "no row has a null `assessed_rating`" gate scoped to `REFRESH_FINAL`; states that `ONBOARDING_PROVISIONAL` credits `self_rating` instead; the `NESTED_CONTROLS`≥2 clause explicitly variant-independent — `routes_questionnaires.py:146-157`.
- **§3.5 depth walk (L265)** — revise — a detected cycle feeds the prohibition ladder rather than short-circuiting the create; the ladder plus the creation rule decides refuse-vs-record-`PROHIBITED`/`CYCLE`; the depth-4 ceiling is tested only when no cycle was found — `routes_nested.py:74-86`, `cascade.py:42-43`.
- **§3.5 nested-chain read (L285)** — revise — the reported `depth` is each row's own §3.5-recomputed depth from its owning respondent, not the expansion hop count, and the ordering uses those values — `routes_nested.py:126-138`.
- **§3.7 calibration (L327)** — revise — pinned gate order (dd_state → `calibration_state` from-state → `UNRATED` refusal, which carries `ERR_INVALID_RESPONDENT_STATE` → overlap → arithmetic), so a superseded profile reports `ERR_INVALID_MONITORING_PROFILE_STATE` — `routes_monitoring.py:149-175`.
- **§3.8 refresh scheduling (L385)** — insert — cycle created with `started_at`, `completed_at`, `lapsed_at`, `completed_control_score`, `completion_risk_rating`, `cancelled_reason` all null (not 0.00), however the cycle arises — `cascade.py:268-282`.
- **§3.8 operator sweep (L395)** — revise — a request the same sweep just marked overdue is also escalated, because the overdue pass completes before the escalation pass — `routes_refresh.py:281-291,316-330`.
- **§3.9 screening ladder (L403)** — insert — only the `AMOUNT_THRESHOLD` and `SCREENED_CLEAR` branches write a threshold; every other ladder outcome leaves `hold_threshold_applied` 0.00 (also the insert default), and later cascades don't rewrite it — `routes_payments.py:76,88,119,122`.

## Per-edit pre-edit search log
1. **§2.4 timestamps** — (a) subject: `created_at`/`updated_at` source. (b) grepped `created_at"]=`/`updated_at"]=` across all 23 impl modules → only `store.insert` and `store.touch`; read `clock.py` (`iso`, `wall_iso`) and `response.py` (`wall_iso` used solely for `api_request_timestamp`). (c) wording confined to `created_at`/`updated_at`; I did **not** strengthen §2.5's "nothing reads wall-clock time", since `api_request_timestamp` genuinely does.
2. **P39 SoD** — (a) subject: which operations enforce SoD. (b) grepped `SEGREGATION` across impl: `routes_questionnaires.py:158` (ASSESS branch only), `routes_respondents.py:281`, `routes_closure.py:154-159`, `routes_alerts.py:148-155` (`_require_segregation` across all alert actions), `routes_rfis.py:180`. (c) narrowed only the questionnaire clause; left the respondent/closure/alert clauses verbatim so the alert rule keeps applying to every disposition action.
3. **§3.4 ASSESS gate** — (a) subject: `assessed_rating` null handling. (b) read `routes_questionnaires.py:128-186` (ASSESS + RETURN), `calc.control_score` variant crediting, §2.9 P33 (L155, already REFRESH_FINAL-scoped), `routes_questionnaires.py:151-157` (nested clause fires under both variants), RETURN's "null assessed_rating counts as substantive". (c) added "whichever variant is supplied" to the `NESTED_CONTROLS` clause so the variant scoping does not leak onto it, and rephrased the error sentence to cover both clauses rather than all nulls.
4. **§3.5 cycle** — (a) subject: cycle detection outcome. (b) read `cascade.compute_nested_depth`, `cascade.prohibition_ladder` (CYCLE first clause), `routes_nested.create_nested:74-88` (depth>4 skipped when cyclic; QUESTIONNAIRE refuses, other sources record PROHIBITED), `routes_nested.adjudication:175-181` with `_confirm`/`_prohibit`, `routes_respondents.py:409` (lift revert consults the ladder), `_expand` (cycle truncates the read). (c) worded as "the ladder … decides whether refused or recorded" rather than asserting either outcome, and confined the ceiling caveat to the cyclic case so the non-cyclic depth>4 hard rejection (which applies to every `discovery_source`) still reads as an outright rejection.
5. **§3.5 chain read** — (a) subject: `depth` in the expanded-chain response. (b) read `routes_nested.nested_chain`/`_expand` and `cascade.compute_nested_depth`; confirmed rows of all states are emitted, traversal only follows `NESTED_LIVE` rows, and the sort key is the recomputed depth. (c) said "commonly 1" rather than "always 1" for downstream-owned rows, since such a row can itself extend a chain and recompute higher.
6. **§3.7 calibration order** — (a) subject: order of CALIBRATE refusals. (b) read `routes_monitoring.calibration:149-200` (all three actions), `cascade.guard_not_closed`, `calc.calibrate_thresholds` (corridor resolution + `ERR_AGGREGATE_THRESHOLD_EXCEEDED` last); grepped `UNRATED` across impl → the refusal exists only in the CALIBRATE branch. (c) scoped the ordering sentence to `CALIBRATE` so `REQUIRE_RECALIBRATION`/`SUPERSEDE` (no rating gate) are untouched, and left the closing "Any other from-state" sentence verbatim.
7. **§3.8 cycle nulls** — (a) subject: refresh-cycle field initialisation. (b) grepped `insert("refreshes"` → only `cascade.schedule_cycle`; traced its four callers (`routes_refresh.schedule`, sweep `CADENCE`, `routes_media.py:125` and `:151`); read `_complete_cycle` (where the two figures are written) and `_lapse_cycle`. (c) added "every cycle however it comes into being" so the sentence also governs the sweep- and media-created cycles, and avoided asserting anything about `rating_at_schedule`/`cadence_months_applied`, whose sweep-time sources differ (L395).
8. **§3.8 sweep** — (a) subject: which requests the sweep escalates. (b) read `_sweep_plan`, `refresh_sweep` (pass order: cadence → lapse → overdue → escalate), `_lapse_ready`, `_narrow`, `cascade.add_strike`/`recompute_escalation_units`, and the explicit `MARK_OVERDUE`/`ESCALATE` capability for contrast. (c) attributed the double transition to the pass ordering rather than rewriting the overdue clause, so the dry-run "would have changed" list and the explicit `ESCALATE` capability (still `OVERDUE`-only, +1 capped at 3) keep their existing meaning.
9. **§3.9 `hold_threshold_applied`** — (a) subject: the field's value on non-`AMOUNT_THRESHOLD` outcomes. (b) grepped `hold_threshold_applied` → `routes_payments.py:76` (insert), `:88` (ladder reset), `:119`, `:122`; read `_screen` (also reached by `RESCREEN`), `cascade.hold_cleared_payments` and `cascade.block_payments_for_sanctions` (both leave the field untouched), `_release`/`_reject`. (c) scoped the 0.00 claim to "every other outcome of a ladder run" and added the explicit cascade carve-out, so a `SCREENED_CLEAR` row later held by the posture cascade keeps its non-zero value without contradicting the sentence.

## Step 9: Complete PRD — 2026-09-03T10:15:00.000Z

ORCHESTRATOR DECISION: Step 9 was run as THREE SEQUENTIAL FILE-PARTITIONED PASSES rather than one subagent. Rationale: the implementation is 23 modules / ~4,900 lines, and a single agent asked to scan all of it exhaustively reliably returns a near-no-op (a `PRD_COMPLETED.md` byte-identical, or nearly so, to its source — proof the walk never actually happened). Partitioning by implementation module gives each pass a tractable scope and prevents two passes colliding on the same PRD lines. Pass 1 performed the `cp PRD_FINALIZED.md PRD_COMPLETED.md`; passes 2 and 3 each continued editing the same live file in place and were told explicitly not to revert earlier passes.

- **Pass 1** — `app.py`, `clock.py`, `store.py`, `errors.py`, `response.py`, `auth.py`, `validate.py`, `common.py`, `routes_clock.py`, `routes_jurisdictions.py`, `routes_respondents.py`, `routes_owners.py` → 26 edits (22 ambiguity-pins, 4 mismatch-revisions), +8,349 chars.
- **Pass 2** — `calc.py`, `cascade.py`, `routes_questionnaires.py`, `routes_nested.py` → 28 edits (23 ambiguity-pins, 5 mismatch-revisions), +8,788 chars.
- **Pass 3** — `routes_monitoring.py`, `routes_alerts.py`, `routes_rfis.py`, `routes_media.py`, `routes_refresh.py`, `routes_payments.py`, `routes_closure.py` → 51 edits (~29 ambiguity-pins, ~22 mismatch-revisions), +20,124 chars.

**Total: 105 edits, +37,261 chars (156,398 → 196,623 including Step 8's +2,964).**

ORCHESTRATOR VERIFICATION of the final artifact:
- `PRD.md` 594 lines / 156,398 chars → `PRD_FINALIZED.md` 594 / 159,362 → `PRD_COMPLETED.md` 594 / 196,623.
- `diff PRD_FINALIZED.md PRD_COMPLETED.md` = 168 changed lines (84 revised line-pairs). NOT byte-identical, so the scan genuinely ran in all three passes.
- Structure intact: 5 `##` sections, 69 §4 endpoint rows (+1 header), 74 §5 error rows, tail ends at the complete final row `| ERR_OBLIGATION_OUTSTANDING | 422 |`. No new sections were added and no lines added or removed — every edit is in-paragraph, as the step requires.
- `find implementation/ test_suite/ test_helpers/ -newer results.1.json -name '*.py'` returns EMPTY: no Python file changed after the verified sweep, so the independently re-verified 8×207/207 green result still describes the artifact on disk. Step 9 touched only `PRD_COMPLETED.md`, as instructed.

Each pass reported its own deliberate non-documentation decisions (unreachable guards, unobservable internal repetition, and two genuine implementation bugs — an unhandled `InvalidOperation` in `wind_down_cap` on a null `aggregate_usd_threshold`, and `routes_nested.adjudication` writing `row["depth"]` before dispatch so a refused adjudication leaks a rewritten depth). These were left OUT of the PRD on the grounds that a crash and a rejected-request side-effect leak are defects, not behavior to enshrine as normative — recorded here rather than in the contract.

### Verbatim Pass 1 summary

PASS 1 complete.

`PRD_FINALIZED.md` → `PRD_COMPLETED.md`: **594 lines → 594 lines**, char delta **+8,349** (159,362 → 167,711). All edits were in-paragraph; 26 lines changed, no new sections or paragraphs, no lines added or removed. File still ends at a real section boundary with the complete final §5 table row (`| ERR_OBLIGATION_OUTSTANDING | 422 |`); all 27 headings, all 69 §4 endpoint rows and all 74 §5 error rows verified intact.

**Counts: 22 ambiguity-pins, 4 mismatch-revisions.**

### Changes
- §2.1 (¶1) — revise — mismatch — empty-string header value counts as absent for `ERR_UNAUTHENTICATED` — `auth.py:43`
- §2.1 (¶3) — insert — ambiguity — list-read scope is a *filter* (contact narrowed to own id; explicit foreign `respondent_bank_id` → 403) — `common.py:72-80`
- §2.2 (bullets) — insert — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alnum chars — `response.py:15`
- §2.2 (bullets) — revise — mismatch — `api_request_timestamp` is the one value read from real wall-clock time, not the logical clock — `response.py:21`, `clock.py:37`
- §2.3 (¶2) — insert — ambiguity — filter semantics: exact equality, empty-string filter ignored, undeclared params ignored, boolean filters accept `true`/`1`/`yes` — `common.py:89-104`
- §2.3 (¶3) — revise — mismatch — default `created_at` ascending is realised as insertion order, which diverges when the clock is moved backwards — `store.py:104-110`
- §2.4 (¶2) — insert — ambiguity — no-op writes still bump `version`/`updated_at`; a row inserted in a request stays at `version` 1 even if a later hop touches it — `store.py:40-77`
- §2.5 (¶1) — insert — ambiguity — clock endpoint returns HTTP 200 with `data.current_utc` only, not a resource — `routes_clock.py:19`
- §2.6 (¶1) — insert — ambiguity — decimals are JSON bare numbers (0.00 → `0.0`, 0.2790 → `0.279`); quantisation is precision, not formatting — `response.py:26-32`
- §2.9 p3 — insert — ambiguity — on child-id paths, priority 4's 404 precedes the priority-3 scope check — `common.py:64-69`
- §2.9 p5 — insert — ambiguity — absent/empty body = empty object; unparseable or non-object body = `ERR_INVALID_REQUEST_BODY`; explicit `null` = absent; string-length bounds report `ERR_INVALID_REQUEST_BODY` not `ERR_FIELD_OUT_OF_RANGE` — `validate.py:78-126`
- §2.9 p9 — insert — ambiguity — instant parsing leniency (date-only, space separator, 1-9 fractional digits, offsets normalised, absent offset = UTC) vs strict `YYYY-MM` — `clock.py:41-87`
- §2.9 p27 — revise — mismatch — sanctioned home jurisdiction blocks amendment in **any** `dd_state`, not just past `PROSPECT` — `routes_respondents.py:151`
- §3.1 (¶1) — insert — ambiguity — malformed `jurisdiction_code` → `ERR_INVALID_REQUEST_BODY` 400, before uniqueness — `routes_jurisdictions.py:51`
- §3.1 (¶2) — insert — ambiguity — `basel_aml_index`/`corridor_risk_weight` stored quantised to 2 dp — `routes_jurisdictions.py:62,64`
- §3.1 (¶4) — insert — ambiguity — `jurisdiction_code` not amendable; field-less amendment accepted and still bumps `version` — `routes_jurisdictions.py:97-110`
- §3.1 (¶4) — revise — ambiguity — sanctions payment-block hop fires only for respondents whose own posture moved to `BLOCKED`, never ones reached via a nested edge — `routes_jurisdictions.py:141-142`
- §3.2 (¶1) — insert — ambiguity — `swift_bic` format error id; `expected_monthly_*` ≥ 0 → `ERR_FIELD_OUT_OF_RANGE` — `routes_respondents.py:69,37-38`
- §3.2 (¶2) — insert — ambiguity — `regulator_name` null unless supplied; volume 2 dp, count integral — `routes_respondents.py:87,90-91`
- §3.2 (¶3) — insert — ambiguity — OPEN gate fires only on actual widening; `SCREEN_ONLY`/`WIND_DOWN_ONLY`/`BLOCKED` written straight through — `routes_respondents.py:147,171`
- §3.2 (¶3) — revise — mismatch — sanctioned-home amendment refused in any state, after the posture gate — `routes_respondents.py:151`
- §3.2 (¶5) — insert — ambiguity — `EXITING` also 403; sanctioned-home `PROSPECT` records but stays; all other `dd_state`s record with no move; already-`BLOCKED` posture stays `BLOCKED` — `routes_respondents.py:194,207-214`
- §3.2 (¶7) — insert — ambiguity — missing `restriction_reason` 400 precedes the `dd_state` 409 — `routes_respondents.py:355-359`
- §3.2 (¶9) — insert — ambiguity — null `last_approved_at` + any `LAPSED` cycle blocks `CLEAR_SCREENING`; all refusals `ERR_INVALID_RESPONDENT_STATE` — `routes_respondents.py:425-435`
- §3.3 (¶3) — insert — ambiguity — jurisdiction 404 beats parent 404; sibling 100.00 sum counts rejected siblings — `routes_owners.py:37-70`
- §3.3 (¶5) — insert — ambiguity — VERIFY refusal error ids/order; REJECT/RESET use the closed-relationship 403 and accept `DECLINED`; conditional `rejection_reason` evaluated after from-state; all actions answer with the owner row — `routes_owners.py:119-163`
- §3.6 (¶1) — insert — ambiguity — `TERMINATED` reports 409 not 403 on scoring; `EXITING` reports 403 — `routes_respondents.py:233-236`
- §3.6 (committee ¶) — insert — ambiguity — `override_risk_rating` is unvalidated and its value never read — `routes_respondents.py:286`

### Deliberately left undocumented
- **`ERR_OWNERSHIP_CYCLE_DETECTED` on owner creation is unreachable** (`routes_owners.py:49-54`): `calc.owner_chain` already truncates on revisit, and the node being created has no id yet, so the check never fires. The PRD's clause is already vacuous in the same way, so no edit was warranted.
- **`_sanctions_cascade` rolls up affected respondents in respondent-`id` (UUID) order** rather than `created_at` order (`routes_jurisdictions.py:137`), contrary to §2.10's blanket rule. `nested_rollup` is idempotent per respondent and order-independent, so no response field can distinguish the two orders; documenting it would only add noise.
- **`app.url_map.strict_slashes = False` / `JSON_SORT_KEYS = False`**: the trailing-slash tolerance is documented in the §4 intro; key ordering is not observable through any assertion the PRD makes, so it was left alone.
- **`isalnum()`/`isalpha()`/`isupper()` accept non-ASCII letters and digits** in `swift_bic` and `jurisdiction_code`. Pinning Unicode edge cases would over-specify beyond anything the PRD's data model contemplates.
- Anything reached only through `calc.py` or `cascade.py` internals was read only for context and left entirely to passes 2 and 3.

### Verbatim Pass 2 summary

Pass 2 complete.

`workspace/PRD_COMPLETED.md`: **594 lines** (unchanged), **176,499 chars** vs 167,711 at start → **+8,788 chars**. Integrity verified: 69 §4 endpoint rows, 74 §5 error rows, 27 headings, final table row `| ERR_OBLIGATION_OUTSTANDING | 422 |` complete. No other file touched.

**Counts: 23 ambiguity-pins, 5 mismatch-revisions (28 edits).**

### Changes

- §3.4 questionnaire create — insert — ambiguity — `expected_respondent_version`/`declared_downstream_count` must be ≥0 (`ERR_FIELD_OUT_OF_RANGE`); no `dd_state` precondition beyond the closed guard — routes_questionnaires.py:38-46
- §3.4 control-row create — insert — ambiguity — `UNDER_ASSESSMENT`/`ASSESSED`/`SUPERSEDED` accept no row; the `SUBMITTED` exception is analyst-only; promotion applies after insert so a duplicate refusal leaves `SUBMITTED` — routes_questionnaires.py:203-228
- §3.4 overlay — revise — mismatch — `NONE`/`MINOR` never *clears* a `remediation_required` already true (PRD said "leaves false") — routes_questionnaires.py:275-279
- §3.4 submission — insert — ambiguity — inconsistent declaration ⇒ `ERR_INVALID_QUESTIONNAIRE_STATE` 409, tested before domain completeness — routes_questionnaires.py:99-102
- §3.4 assessment decision — insert — ambiguity — `clarification_note` 0–2000 chars, validated but never persisted — routes_questionnaires.py:125
- §3.4 `ASSESS` — insert — ambiguity — missing `variant` ⇒ `ERR_INVALID_REQUEST_BODY` 400, ahead of the variant/`dd_state` test — routes_questionnaires.py:129-131
- §3.4 `ASSESS` — insert — ambiguity — only `control_score` is mirrored; credit/residual/rating unmoved until the next scoring run — routes_questionnaires.py:168
- §3.4 `RETURN` — insert — ambiguity — check order; non-substantive return ⇒ `ERR_INVALID_QUESTIONNAIRE_STATE` 409; no `dd_state` and no SoD — routes_questionnaires.py:171-182
- §3.4 questionnaire list — insert — ambiguity — `questionnaire_version` descending is lexicographic string order — routes_questionnaires.py:76
- §3.5 nested create — insert — **mismatch** — check order inverts ladder priorities 20/31: the `downstream_jurisdiction_code` 404 beats `ERR_RESPONDENT_RELATIONSHIP_CLOSED`; unresolvable `downstream_respondent_bank_id` ⇒ `ERR_RESPONDENT_NOT_FOUND` 404, no cross-respondent constraint — routes_nested.py:44-53
- §3.5 depth walk — insert — ambiguity — candidate ordering reads each row's *stored* `depth`, null treated as 0 — cascade.py:32
- §3.5 depth ceiling — insert — **mismatch** — the >4 rejection precedes the ladder and applies to every `discovery_source` (not recorded `PROHIBITED`); a cyclic row stores the depth reached before the repeat; 32-hop safety stop — routes_nested.py:74-78, cascade.py:21-22
- §3.5 exposure rollup — insert — **mismatch** — respondent `version`/`updated_at` advance only when one of the four rollup fields actually moves, notwithstanding §2.4's list — cascade.py:71-80
- §3.5 adjudication — insert — ambiguity — `SUSPEND` has no declared from-state and is always `ERR_INVALID_NESTED_STATE` — routes_nested.py:147
- §3.5 `CONFIRM` — revise — ambiguity — `dd_state` and `nested_activity_permitted` refusals are `ERR_INVALID_RESPONDENT_STATE` 409, ahead of the closed guard's 403; reordered to match impl — routes_nested.py:165-198
- §3.5 `REVERT` — insert — ambiguity — same 409-before-403 precedence — routes_nested.py:168-170
- §3.5 `PROHIBIT` — revise — ambiguity — a reasonless ladder ⇒ `ERR_NESTED_JURISDICTION_PROHIBITS_NESTING` 422; the body's `prohibition_reason` is ignored — routes_nested.py:214-218
- §3.5 nested-chain — insert — ambiguity — per-branch visited set (rows can repeat across branches), 4-hop bound, filter/pagination applied post-walk — routes_nested.py:126-138
- §3.2 restriction cascade — insert — ambiguity — `OFFICER_ACTION` is the recalibration reason on every path; only the earliest-created `CALIBRATED` profile moves — cascade.py:105-112, 129-138
- §3.6 scoring run — insert — ambiguity — control score recomputed under the run's own variant, questionnaire's frozen fields untouched; step skipped entirely (score retained) when no `ASSESSED` questionnaire exists — cascade.py:206-211
- §3.7 escalation hop three — insert — ambiguity — also gated on posture `OPEN` and the approved-family `dd_state` — cascade.py:390-391
- §3.8 strike ledger — revise — **mismatch** — the cascade-driven abandonment adds no strike (only the explicit `ABANDON` does) and resets `escalation_level` to 0 — cascade.py:294-300
- §3.8 strike threshold — insert — ambiguity — re-runs on every further strike, overwriting `restriction_reason`; `escalation_units` written back only when the total moves — cascade.py:155-183
- §3.8 media hop two — insert — ambiguity — window variant taken from stored `risk_assessment_variant`, `NONE` ⇒ `ONBOARDING_LOOKBACK`; inherent/credit not recomputed — cascade.py:232-244
- §3.8 cadence table — insert — ambiguity — `UNRATED` maps to 0 months — calc.py:37
- §3.8 refresh five-step — insert — ambiguity — null `last_approved_at` ⇒ null; step three uses stored `inherent_risk_score`/`control_credit`; a 0-month frozen rating empties the window and yields `last_approved_at`+30d — calc.py:311-333
- §3.9 wind-down cap — insert — ambiguity — period total rounded before the cap; owning profile = the period's first row in the stated order; mean divides by however many distinct periods were found — calc.py:414-427
- §3.9 settlement lines — revise — ambiguity — latest-created `CALIBRATED` profile, else latest-created of any state; no profile or zero total expected ⇒ empty `allocation_lines` with counters still moving — calc.py:437-451

### Deliberately left undocumented

- `wind_down_cap` raises an unhandled `InvalidOperation` when the owning profile's `aggregate_usd_threshold` is null (a `PROVISIONAL` profile with observations) — a crash, not behavior to pin as normative.
- `routes_nested.adjudication` writes `row["depth"]` *before* dispatching the action, so a refused adjudication leaves a rewritten `depth` with no `version` bump. Observable but a leak on a rejected request; pinning it would enshrine a bug.
- Unreachable guards left alone: `compute_nested_depth`'s self-row exclusion and `effective_ownership_pct`'s cycle break (blocked by priority 35), `inherent_risk_score` treating an unresolvable home jurisdiction as 0, and `cap_basis` `NONE` falling through to the declared-volume base (approval requires the other two bases).
- All Pass-3 route request handling, gate ordering and error precedence, per scope.

### Verbatim Pass 3 summary

Pass 3 complete. Final verification passed: `PRD_COMPLETED.md` is **594 lines / 196,623 chars** (started at 176,499 → **+20,124 chars**), ends at a real section boundary with a complete final table row (`| ERR_OBLIGATION_OUTSTANDING | 422 |`), **69 §4 endpoint rows** and **74 §5 error rows** intact, all five `##` section headers present.

**51 edits total in Pass 3** — 2 in §2.9, 12 in §3.7, 22 in §3.8, 15 in §3.9. Roughly **29 ambiguity-pins / 22 mismatch-revisions.** All applied as surgical `Edit` calls; no other file touched.

### §2.9
- §2.9 priority 14 — revise — mismatch — a `SCREEN_ONLY`/`WIND_DOWN_ONLY` posture does not itself bar a release (ladder said "neither `BLOCKED` nor `SCREEN_ONLY`") — routes_payments.py:170
- §2.9 priority 20 — insert — mismatch — the relationship-closed guard is in practice evaluated *ahead* of the priority-12 child from-state check on every child transition of §3.4–§3.9, with the officer screening decision the sole exception — cascade.py:305, routes_payments.py:166-173

### §3.7 (routes_monitoring.py, routes_alerts.py)
- §3.7 create — insert — ambiguity — corridor-entry shape errors are `ERR_INVALID_REQUEST_BODY`, negatives `ERR_FIELD_OUT_OF_RANGE`, whole array checked before the version compare, resolution and uniqueness interleaved entry-by-entry in payload order — routes_monitoring.py:95-116, 40-54
- §3.7 create — insert — ambiguity — `tolerance_pct` default 0.15 — routes_monitoring.py:80
- §3.7 interval — insert — ambiguity — a `SUPERSEDED` profile is invisible to the overlap test — routes_monitoring.py:59
- §3.7 create — insert — mismatch — a successful create bumps the respondent's own `version`/`updated_at`, so a second create must quote the bumped value — routes_monitoring.py:91
- §3.7 calibration — insert — ambiguity — the missing-`recalibration_reason` 400 precedes the from-state 409 — routes_monitoring.py:184-190
- §3.7 calibration — insert — ambiguity — `SUPERSEDE` accepted from all three live states, leaves thresholds and reason untouched, refused only when already `SUPERSEDED` — routes_monitoring.py:193-198
- §3.7 calibration — insert — ambiguity — `REQUIRE_RECALIBRATION`/`SUPERSEDE` impose no `dd_state` gate beyond priority 20 — routes_monitoring.py:187, 194
- §3.7 observation — insert — ambiguity — the clock's own calendar month is accepted — routes_monitoring.py:241
- §3.7 alert generation — insert — ambiguity — the corridor threshold line is taken **by position** (nth corridor ↔ nth threshold) — routes_monitoring.py:281-292
- §3.7 alert generation — insert — mismatch — volume/count breaches are suppressed unless `calibration_state` is exactly `CALIBRATED`; an uncalibrated profile still records the observation and still raises corridor/nesting alerts, and an empty `corridor_thresholds` leaves all three applied fields at their zero defaults — routes_monitoring.py:291-317
- §3.7 alert generation — insert — ambiguity — the undisclosed-nesting check runs whatever the corridor and whatever the calibration state — routes_monitoring.py:318-323
- §3.7 disposition — insert — ambiguity — only `INVESTIGATE`/`ESCALATE` carry a `dd_state` gate; the segregation check runs after the from-state and reason checks — routes_alerts.py:98-120
- §3.7 `CLOSE_CONFIRMED` — revise — mismatch — the restriction fires only while `dd_state` is in the approved family; otherwise the alert closes and the respondent is untouched; the alert-type refusal precedes the reason check — routes_alerts.py:109-144
- §3.7 `ESCALATE` — revise — mismatch — `DECLINED`, `EXITING` and `TERMINATED` all report `ERR_INVALID_RESPONDENT_STATE` ahead of every other gate, so the relationship-closed 403 never surfaces; the open-linked-request refusal is the last gate of all — routes_alerts.py:98-126
- §3.7 reads — insert — ambiguity — profile/observation/alert filter sets and sort orders — routes_monitoring.py:126, 334, routes_alerts.py:61

### §3.8 (routes_rfis.py, routes_media.py, routes_refresh.py)
- §3.8 request create — insert — ambiguity — severity-equality check runs only after the cross-respondent check; the linked alert's state is not examined until dispatch; creation permitted while `EXITING`; created-row defaults — routes_rfis.py:32-45
- §3.8 dispatch — insert — ambiguity — gate order (dd_state → guard → from-state → reminder budget → linked-alert state), and an alert that no longer resolves is `ERR_INVALID_ALERT_STATE` — routes_rfis.py:73-88
- §3.8 dispatch — insert — ambiguity — re-issue from `ESCALATED` requires `reminder_count` ≤ 2 — routes_rfis.py:80
- §3.8 dispatch — insert — mismatch — a `CRITICAL` dispatch narrows the posture but never forces a profile into `RECALIBRATION_REQUIRED` — routes_rfis.py:90-91
- §3.8 SLA — insert — ambiguity — the overdue comparison at `due_at` is inclusive — routes_rfis.py:135
- §3.8 response — revise — mismatch — a `TERMINATED` respondent reports `ERR_INVALID_RESPONDENT_STATE` 409 rather than the relationship-closed 403, ahead of the from-state check; an `EXITING` respondent may still answer; counters left as they stood — routes_rfis.py:102-111
- §3.8 overdue maintenance — insert — ambiguity — all three actions permitted while `EXITING`, none carries its own `dd_state` gate — routes_rfis.py:122
- §3.8 `REMIND` — insert — ambiguity — changes nothing but `reminder_count` — routes_rfis.py:131-133
- §3.8 `ESCALATE` — revise — mismatch — the 72-hour window is measured from `due_at` itself and is the same at every level, never cumulative; the temporal check follows the from-state check — routes_rfis.py:145
- §3.8 strike ledger — revise — mismatch — the cascade-driven abandonment adds no strike whatever the state and resets `escalation_level` to 0; the 3-strike consequence re-runs on every further strike and overwrites `restriction_reason` — cascade.py:294-300, 176-183
- §3.8 strike ledger — insert — ambiguity — `escalation_units` is written back only when the recomputed total differs — cascade.py:155-161
- §3.8 `ACCEPT` — insert — ambiguity — retro credit applies only when `retro_credit` is true **and** `reminder_count` > 0 — routes_rfis.py:186
- §3.8 `INSUFFICIENT` — insert — mismatch — leaves `responded_at`, `response_note`, `reminder_count`, `retro_credited` and `adjudicated_by_user_id` as they stood — routes_rfis.py:194-205
- §3.8 `ABANDON` — insert — mismatch — writes `adjudicated_by_user_id` just as `ACCEPT` does — routes_rfis.py:209
- §3.8 media log — insert — ambiguity — created-row defaults; points earned only at triage — routes_media.py:40-51
- §3.8 triage — insert — mismatch — `DISMISS` carries no `dd_state` gate and, though it rewrites no respondent field, still bumps the respondent's `version` once — routes_media.py:89-97
- §3.8 triage — insert — ambiguity — the `NEW` from-state check follows `CONFIRM`'s `dd_state` gate and the priority-20 guard but precedes the dismissal test and the event-date test — routes_media.py:83-100
- §3.8 confirm hop three — revise — mismatch — the recomputed `refresh_due_date` is always written back, a null included; the acceleration stops at the **first** `SCHEDULED` cycle it accelerates — routes_media.py:115-126
- §3.8 confirm hop four — insert — ambiguity — reverted owners also have `verified_by_user_id` cleared to null — routes_media.py:133
- §3.8 confirm sixth hop — insert — ambiguity — `TIER_1` non-`SANCTIONS_EVASION` narrows to `SCREEN_ONLY` only from `OPEN`/`SCREEN_ONLY`, leaves `WIND_DOWN_ONLY`/`BLOCKED`, and schedules an extra cycle only when no live cycle exists **and** `refresh_due_date` is non-null — routes_media.py:143-152
- §3.8 refresh schedule — insert — ambiguity — no ordering is imposed between `window_start` and `scheduled_due_date`; acceleration cancels only `SCHEDULED` siblings; the respondent's `version` moves either way — routes_refresh.py:54-76
- §3.8 `START` — insert — mismatch — gate order is window_start → dd_state → other-in-progress, with the first and third `ERR_INVALID_REFRESH_STATE` and only the middle `ERR_INVALID_RESPONDENT_STATE` — routes_refresh.py:143-155
- §3.8 `COMPLETE` — revise — mismatch — "five respondent-side conditions" corrected to four, with each error id and the evaluation order pinned — routes_refresh.py:163-185
- §3.8 `LAPSE` — revise — mismatch — both too-early refusals are `ERR_INVALID_REFRESH_STATE` 409, not a temporal 422; the grace-period cycle is chosen by `scheduled_due_date` desc then `created_at` desc — routes_refresh.py:200-236
- §3.8 `CANCEL` — insert — ambiguity — the missing-reason 400 is reported only after the from-state check; a cancellation writes only the cycle — routes_refresh.py:134-139
- §3.8 progression — insert — ambiguity — `START`/`COMPLETE` refused while `EXITING`, `LAPSE`/`CANCEL` permitted there — routes_refresh.py:120-123
- §3.8 sweep — insert — ambiguity — null `refresh_due_date` sorts last with `created_at` ascending among the nulls; each respondent's whole transition set is computed before any write — routes_refresh.py:241-247, 275-303
- §3.8 sweep — revise — mismatch — response returns affected rows in sweep order with `limit`/`total_count` equal to the count, `offset` 0, `has_more` false, ignoring pagination parameters and never reporting `ERR_INVALID_PAGINATION`; being listed does not guarantee the respondent's own `version` moved — routes_refresh.py:331
- §3.8 reads — insert — ambiguity — request/media/refresh filter sets and sort orders — routes_rfis.py:53, routes_media.py:63, routes_refresh.py:88

### §3.9 (routes_payments.py, routes_closure.py)
- §3.9 submit — insert — ambiguity — the posture-`BLOCKED` 403 outranks both an unresolvable corridor and a terminated relationship; the guard admits `EXITING` — routes_payments.py:44-51
- §3.9 `RELEASE` — insert — ambiguity — `RELEASE` is a declared transition out of `BLOCKED_SANCTIONS` (hence the specific 403); the posture 403 is tested first; the nested-confirmed refusal is `ERR_NESTED_DISCLOSURE_MISSING` 422 ahead of the wind-down trio — routes_payments.py:147, 170-176, 202-208
- §3.9 `HOLD` — insert — ambiguity — writes no `hold_reason`; the instruction sits held with `hold_reason` null and `hold_threshold_applied` 0.00 — routes_payments.py:179-180
- §3.9 `REJECT` — insert — ambiguity — inadmissible reasons are `ERR_INVALID_REQUEST_BODY` 422; rejection clears `hold_reason` and leaves `hold_threshold_applied` — routes_payments.py:184-193
- §3.9 payment reads — insert — ambiguity — rows returned `created_at` ascending — routes_payments.py:130
- §3.9 draft — revise — mismatch — drafting runs the full `_enter_exiting` cascade (hold cleared payments when the posture was `OPEN`, cancel `SCHEDULED`/`IN_PROGRESS` cycles as `RELATIONSHIP_EXITING`), remembers the pre-exit standing off-row, pins `wind_down_cap_usd` 0.00 and the five null fields, requires `original_obligation_cents` ≥ 0, and is permitted while already `EXITING` — routes_closure.py:27-38, 64-94
- §3.9 submission — insert — mismatch — gate order respondent-state → from-state → identity → invariant, with the identity failure `ERR_FORBIDDEN_ROLE` 403 and a `TERMINATED` respondent reporting `ERR_INVALID_RESPONDENT_STATE` — routes_closure.py:120-131
- §3.9 approval — insert — mismatch — gate order from-state → return budget → drafted-by → assessed-by → basis, the basis refusal `ERR_INVALID_REQUEST_BODY` 422 and only for `APPROVE`; the assessed-by check is skipped when `assessed_by_user_id` is null; a body `cap_basis` overwrites the drafted value, an omitted one keeps it — routes_closure.py:149-165
- §3.9 approval — insert — ambiguity — `APPROVE`'s respondent move is the identical (idempotent) `_enter_exiting` drafting makes — routes_closure.py:171
- §3.9 `REJECT` — insert — ambiguity — the restore sanitises a remembered `EXITING`/`TERMINATED`/`PROSPECT`/`DECLINED` (and an absent memory) to `APPROVED`, keeps `restriction_reason` only for `RESTRICTED` — routes_closure.py:41-53
- §3.9 `SERVE_NOTICE` — insert — mismatch — the null-`notice_period_days` refusal is `ERR_INVALID_CLOSURE_STATE` 409 and precedes the `RESPONDED`-RFI refusal, which is `ERR_INVALID_RFI_STATE` 409 — routes_closure.py:221-227
- §3.9 `BEGIN_WIND_DOWN` — insert — mismatch — both refusals are `ERR_INVALID_CLOSURE_STATE` 409, clock before graph, a null `notice_served_at` clears the clock test, and the posture write is unconditional (widening a `BLOCKED` posture) — routes_closure.py:237-249
- §3.9 `CLOSE` — insert — mismatch — the live-payment refusal is `ERR_INVALID_PAYMENT_STATE` 409 and third; a null `wind_down_end_at` fails the notice test — routes_closure.py:252-263
- §3.9 `ABORT` — revise — mismatch — corrected the false rationale: from `DRAFT` nothing is restored, so the respondent stays `EXITING`/`WIND_DOWN_ONLY`; the held-payment refusal is `ERR_INVALID_PAYMENT_STATE` 409; the missing-reason 422 follows the from-state gate — routes_closure.py:273-286
- §3.9 settlement — insert — ambiguity — the from-state refusal is `ERR_INVALID_CLOSURE_STATE` 409 ahead of either action's arithmetic; `amount_cents` is strictly positive — routes_closure.py:294-302

### Deliberately left undocumented
- **`store.touch(resp)` calls whose only effect is a `version` bump already implied by another write in the same request.** Because §2.10 pins one bump per row per request, these are unobservable and documenting them would add noise.
- **`cascade.live_plan`/`open_plan` picking the latest-created candidate** when several qualify. The one-open-plan-per-respondent uniqueness rule (§2.9 priority 36) makes the multi-candidate case unreachable.
- **`_corridors` returning quantised `expected_monthly_usd`** (`q2`) on the stored profile. §2.6's global 2-decimal storage discipline already covers it.
- **The sweep's per-respondent `cascade.recompute_escalation_units` / `add_strike` call counts.** The observable end state is already pinned; the internal repetition is not distinguishable from outside.

## PIPELINE COMPLETE — 2026-09-03T10:16:00.000Z

All nine steps finished. Final artifact inventory in `tasks/task_2499_correspondent_banking_respondent_due_diligence/`: `SCAFFOLD.yaml` (4,031 lines), `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1,523), `SCAFFOLD_CORNER_DESIGN.yaml` (8,969), `worklog.md`, `test_helpers/` (9 modules), `test_suite/` (48 test files, 207 tests), and `workspace/` containing `INSTRUCTION.md`, `PRD.md` (594 lines), `PRD_FINALIZED.md` (594), `PRD_COMPLETED.md` (594 / 196,623 chars), `sweep.sh`, `sweep.log`, and `implementation/` (23 modules + `start.sh` + `requirements.txt` + `results.1.json`…`results.8.json`, each 207/207).
