# Worklog — task_1733_consumer_complaint_management_regulator

## Step 1: Create Task Directory — 2026-08-14T12:05:00.000Z

Directory `tasks/task_1733_consumer_complaint_management_regulator/` and `workspace/` were pre-created and pre-assigned by the pipeline invoker. Step 1 treated as DONE per instructions.

## Step 3: Copy Shared Files — 2026-08-14T12:06:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1733_consumer_complaint_management_regulator/workspace/INSTRUCTION.md`. (Done early, in parallel with Step 2, since the copy has no dependency on the scaffold.)

## Step 2: Generate Scaffold — 2026-08-14T12:46:00.000Z

All three files are complete, syntactically valid, and pass `scaffold_lint.py` with a clean verdict. Final summary:

## Task 1733 — Consumer Complaint Management & Regulator Response: scaffold complete

**Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1733_consumer_complaint_management_regulator/`):**
- `SCAFFOLD.yaml` — §1.0–§1.7 (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top-level key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top-level key `scaffold_corner_design`

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (62 endpoints, 12 entities, 18 §1.8 instances, 50 active §1.9 instances, 597 calls scanned, 0 violations.)

**Design (harder-than-expert target, compliance/audit archetype + workflow orchestration; hybrid topology; compound posture-driven state; segregation-of-duties role model):**

- **Entities (12):** Product (posture-gating computed aggregates), Channel, TaxonomyCategory (self-referential hierarchy), ResponseTemplate (governance), Complaint, IntakeEvent (append-only audit log), RegulatoryReferral (15-day CFPB deadline), RootCauseAnalysis (30-day deadline), RemediationDecision (restitution ledger), QualityReview (half-open sampling windows), EscalationCase, TrendSnapshot (closed-interval windows, early-warning).

- **State machines (8):** Complaint is cyclic (RESOLVED → REOPENED → INVESTIGATING loop, 13 transitions with 5 withdraw from-states); RegulatoryReferral is cyclic (RESPONSE_SUBMITTED ↔ REOPENED_BY_REGULATOR with fixed-deadline timeliness re-derivation); Product is posture-driven compound (OPEN/WATCH/FROZEN derived from complaint+RCA aggregates, gates intake); RemediationDecision has a compensation branch (APPROVED → REVERSED); plus RootCauseAnalysis (with system supersede), ResponseTemplate (supersede-on-publish), QualityReview, EscalationCase.

- **Calculations (9):** dual-variant complaint aging (calendar 9 vs business 6 days for the same window) and dual-variant retention (null vs frozen+5y); pinned per-line-floor-then-sum restitution rounding (101 vs 102 cents); 4-input non-linear timeliness score with floor-before-bonus ordering (95 and 2 pinned); early-warning threshold with pinned circular-dependency evaluation order (5000 bps warns, 3333 doesn't, empty window never warns); product posture thresholds; referral 15-day due date; portal-channel atomic referral auto-creation.

- **Difficulty rules:** all 9 rules × 2 instances each = 18 instances — including two OCC concurrency rules (taxonomy recode, remediation create; both 412 with `${var}` version discipline), two cross-entity state gates (resolve↔QA review, withdraw↔referral), two interval semantics (half-open review windows where touching endpoints are allowed vs closed snapshot windows where a shared boundary overlaps), and two compensating invariants (restitution ledger conservation; single-ACTIVE-template-per-pair).

- **Corner design:** 53 instances (51 active + 2 `excluded_because` stubs) across all nine claim-extraction sections: entities 7, state_machines 9, calculations 5, validations 10, endpoints 4, errors 5, rbac 6, cross-cutting layers 5, consistency 2 — covering RBAC denials per role, terminal lockdowns, idempotency, inclusive/exclusive deadline boundaries (RCA 30-day inclusive, retention 5y strict, referral 15-day inclusive to the second), defaults, immutability of the audit log, pagination envelope, and 90-day window expiry via the logical clock (startup default 2026-08-01T00:00:00Z).

**Process note:** midway, a helper script accidentally truncated SCAFFOLD.yaml (an errant `open(p,'w')`); the file was fully rewritten from the design plan and re-validated — no content was lost in the final artifacts. All formula-derived asserts were pre-computed by executing the formulas (restitution 101, ages 9/6, scores 95/2, rates 5000/3333 bps, deadlines 2026-08-16/2026-08-31, retention 2031-08-02/2031-08-05).

Orchestrator verification: all three files present on disk (SCAFFOLD.yaml 1740 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1192 lines, SCAFFOLD_CORNER_DESIGN.yaml 2122 lines) and parse as valid YAML.

## Step 4: Generate PRD — 2026-08-14T12:55:00.000Z

The PRD is complete and verified. Final summary:

## Summary

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1733_consumer_complaint_management_regulator/workspace/PRD.md` — 317 lines, ~48.5 KB, ending cleanly at the §5 error table with no audit footer.

### Section list
- **§1. Introduction** — 3 paragraphs (regulatory pain point → system scope → audience)
- **§2. Global Specifications** — 10 subsections: 2.1 RBAC (7 roles, opaque identities, header contract), 2.2 API Response Structure (verbatim block, byte-identical to `section-2.2-response-structure.md`), 2.3 Pagination (limit 10/1/100, offset 0, `created_at` asc), 2.4 Common Resource Properties (incl. `IntakeEvent`/`TrendSnapshot` carrying only `id`+`created_at`), 2.5 Logical Clock (startup default 2026-08-01T00:00:00Z, posture recompute on set), 2.6 Validation Order (explicit 5-stage pipeline), 2.7 OCC (`expected_complaint_version` on taxonomy recodes + remediation creates → `ERR_STALE_VERSION` 412), 2.8 Monetary Precision, 2.9 Nested Resource Retrieval (left-to-right, all path-param names backticked), 2.10 Audit Trail (15 event types, ordering)
- **§3. Business Logic** — 10 subsections organized by lifecycle: reference data, intake/referral auto-creation, triage/investigation/recode, RCA, drafting/QA/resolution/reopen/withdraw + both age calculations, remediation/restitution (per-line-floor-then-sum pinned), QA review windows (half-open overlap), referral lifecycle + full timeliness score formula, escalations + template governance, trend snapshots + early warning + posture machine
- **§4. Endpoint Definitions** — 4-column table, all 62 endpoints
- **§5. Error Code Catalogue** — 2-column table, all 24 errors

### Hard contract results
- **Contract 1 (Field-Name Coverage):** PASS — 85 required identifiers (entity fields + endpoint inputs + query params + path params + headers), 0 missing. Two repairs applied during the pass: `event_type` added to §2.10; `X-Manager-Authority` re-worded so the header name appears as a bare backticked token; path-param names (`complaintId`, `productId`, etc.) enumerated in §2.9.
- **Contract 2 (Rule Coverage):** PASS — all 9 calculations expressed as precise prose with constants embedded (15 days, 30 days, 5 years, 2500000-cap, 1000000 high-value, 3/5000/10 EW thresholds, 3/5 posture thresholds, 3 holidays, 10000 bps default); both OCC rules expressed with endpoint + field + `ERR_STALE_VERSION`/412; all state transitions across the 8 machines named as backticked `FROM → TO` pairs with preconditions paired to error IDs; multi-hop cascades (regulator-reopen 3-hop, RCA-substantiated hop-2, template supersede-on-publish, remediation-create bumps complaint version) each stated; validation priority stated as an explicit ordered pipeline in §2.6.
- **Contract 3 (§3 Path Purity):** PASS — 429 backticked tokens scanned in §3, 0 paths, 0 bare HTTP methods, 0 method+path tokens; endpoints referenced only via state-pair framing, role+verb, or capability description.

### Deliberate compressions
- The 5 identical withdraw transitions (`INTAKE|TRIAGED|INVESTIGATING|RESPONSE_DRAFTED|RESPONSE_QA → WITHDRAWN`) are rendered once as "any non-terminal state" with the from-set enumerated, matching the scaffold's shared precondition/side-effect block — no rule loss since all five share identical preconditions and side effects.
- Similarly the two `start_investigation` transitions (`TRIAGED` and `REOPENED → INVESTIGATING`) and the two referral `submit_response` transitions (`OPEN` and `REOPENED_BY_REGULATOR → RESPONSE_SUBMITTED`) are rendered as single rules with both from-states named, preserving the scaffold's shared preconditions and the pinned "deadline does not extend on reopen" rule for the reopened branch.

Orchestrator verification: workspace/PRD.md present (317 lines).

## Step 6: Generate Implementation — 2026-08-14T13:26:00.000Z

Implementation complete and verified. Summary below.

## File inventory — `workspace/implementation/`

| File | Role |
|---|---|
| `start.sh` | Foreground launcher, guarded pip install, `exec python3 app.py`, `0.0.0.0:$PORT` (default 10000) |
| `requirements.txt` | flask>=3.0 |
| `app.py` | App factory, blueprint registration under `/complaint-office`, envelope error handlers (incl. 404/405 → `ERR_NOT_FOUND`) |
| `db.py` | In-memory store (dicts keyed by id), logical clock (default exactly `2026-08-01T00:00:00Z`), monotonic sequence — no seeding, byte-fresh per boot |
| `errors.py` | `ApiError` + all 24 error IDs from the §5 catalogue |
| `response.py` | Envelope: `meta.api_request_id` (`req_…`), `api_request_timestamp` (3-fractional-digit ISO), `response_type`, `data`; list meta adds `limit`/`offset`/`total_count`/`has_more` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (401 → 403 order), body/field/enum/datetime validators, pagination params (default 10, min 1, max 100) |
| `timeutil.py` | Version-robust ISO-8601 parser, millisecond formatter, floor/trunc day math, `add_years` (Feb 29 → Feb 28), business-day counter with the fixed 2026 holiday set |
| `services.py` | All 9 calculations, derived-field reconciliation, event appender, serializers (IntakeEvent/TrendSnapshot omit `updated_at`/`version` per §2.4) |
| `routes_admin.py` | Clock, products (+unfreeze, per-product complaints, trend snapshots), channels, taxonomy, templates |
| `routes_complaints.py` | Intake (+atomic portal referral), reads, events, all 9 complaint actions |
| `routes_referrals.py` / `routes_rcas.py` / `routes_remediation.py` / `routes_reviews.py` / `routes_escalations.py` | Child-resource lifecycles |

## Coverage
- **62/62 endpoints** (verified by route-map introspection), each with the exact RBAC role set from the §4 table.
- **All 9 calculations**: calendar/business ages (frozen at terminal, live otherwise), per-line-floor-then-sum restitution, pinned-order timeliness score (floor before bonuses, double clamp, null until first referral submission), closed-interval early-warning (empty window never warns), posture thresholds (FROZEN ≥ 5, WATCH ≥ 3 or early-warning), retention +5y with leap rule, referral +15d due date, portal auto-referral with `AUTO-<id>` default.
- **All 8 state machines** with side effects: complaint lifecycle (incl. reopen loop, withdraw guard), referral cycle with the 3-hop regulator-reopen cascade and non-extending deadline, RCA supersede-on-create, remediation SoD + `X-Manager-Authority: true` cap (2 500 000), template supersede-on-publish and in-use retire block, half-open review-window overlap, closed-interval snapshot-window overlap, manual/system unfreeze.
- **Validation pipeline** per §2.6: auth → RBAC → existence → shape → business, with SoD surfacing before state checks and `ERR_STALE_VERSION` (412, OCC on both `taxonomy_recodes` and `remediation_decisions`) always last.

## Smoke-test result
Four scripts run against fresh `start.sh` boots: full happy path (intake→referral→RCA→draft→QA→resolve), remediation OCC/SoD/cap/reverse, qa_fail + window overlap, escalation blocking, regulator-reopen cascade, RCA-deadline inclusive boundary, retention expiry at `purge_at`, posture WATCH/FROZEN transitions and system path back, early-warning snapshots, auth 401/403, retired-category 409s, frozen-age reads, and fresh-boot emptiness with default-clock stamping — **all pass**. Server booted and served HTTP in ~2 s on every invocation; no state carried between reboots.

## Step 5: Generate Unit Tests — 2026-08-14T13:45:00.000Z

Generation complete and fully verified. Summary:

## Tests generated

**Queue A (Difficulty): 36 tests** — 2 per instance × 18 instances, all translated and PRD-adjudicated:
- `dual_variant_calc` (2 instances × 2): calendar-vs-business aging divergence (two windows), per-line-floor-vs-sum-first restitution (two line-sets)
- `combinatorial_formula` (2×2): timeliness score 95 (on-time + QA PASS + high-value) and 80 (on-time + QA FAIL + high-value); early-warning at exactly 5000 bps and via the open-count branch with rate 0
- `non_linear_state_machine` (2×2): RESOLVED→REOPENED→INVESTIGATING state restore + repeated loop; referral reopen cycle going LATE against the unchanged deadline + staying ON_TIME before it
- `transitive_cascade` (2×2): regulator-reopen 3-hop cascade + no-cascade when parent not RESOLVED; 5th SUBSTANTIATED RCA freezing a product + 4 staying WATCH
- `priority_pair_validation_conflict` (2×2): SoD-beats-state on qa_fail after resolution + isolated SoD single failure; template-not-active beating ERR_RCA_REQUIRED + isolated template-not-active
- `boundary_precision_check` (2×2): referral deadline at/one-second-after/one-second-before; empty window never warns + sub-minimum count never warns at 10000 bps
- `cross_entity_state_dependency` (2×2): resolve gated on QA PASS (FAIL history + pending review) + resolve succeeding after later PASS; withdraw gating (closed referral succeeds; REOPENED_BY_REGULATOR blocks)
- `resource_temporal_overlap` (2×2): QA half-open adjacency allowed/interior rejected + completed review frees window; snapshot closed-interval shared-boundary overlap in both directions
- `compensating_invariant` (2×2): approve→reverse ledger restoration + approve→mark_paid ledger split; publish-supersede single-ACTIVE invariant + cross-pair isolation

**Queue B (Corner): 50 tests** — 1 per non-stub instance across all 9 sections (entities 7, state_machines 9, calculations 5, validations 10, endpoints 4, errors 4, rbac 6, cross_cutting 4, consistency_model 1).

## Instances skipped

None — all 18 active §1.8 instances and all 50 active §1.9 instances passed the PRD-first two-condition filter. The 3 `excluded_because:` stubs (`error_rca_required_on_draft_response`, `cascading_side_effects_resolve_decrements_open_count`, `immediate_consistency_cascade_visible_in_same_read_after_trigger`) were correctly left untranslated; their difficulty-instance cross-references were verified to resolve.

## Verification results

- `py_compile` + import of all helpers and test files: clean; `pytest --collect-only`: **86 tests collected**
- Tag audit (AST-based): every test has exactly one `Design:` line, at docstring end, resolving to a real instance; difficulty ≥2/instance and corner ≥1/instance both satisfied (36 + 50 = 86 == translated instance count)
- Citation audit: a distinctive ≥8-word window of every quoted PRD citation survives whitespace-normalized literal match against PRD.md (86/86)
- No `skip`/`skipif`/`xfail` markers; no scaffold references in generated code

## File inventory

- `test_helpers/`: `__init__.py` (barrel), `types.py` (11 status enums + 12 TypedDicts; append-only entities omit `updated_at`/`version`), `api_client.py` (66 methods covering all §4 endpoints), `api_errors.py` (24 error IDs + status map registered with framework), `assertions.py` (per-entity assertions + instant-comparison helper tolerant of ISO format variants), `factories.py`, `constants.py` (all PRD thresholds), `test_users.py` (7 role header sets + per-id builders + `X-Manager-Authority` helper), `fixtures.py` (composite lifecycle/threshold/posture fixtures using lenient setup validation)
- `test_suite/`: `conftest.py` (api + role-header fixtures), `test_01_reference_data.py` (7), `test_02_complaint_lifecycle.py` (9), `test_03_calculations.py` (13), `test_04_validations.py` (14), `test_05_endpoints_and_consistency.py` (5), `test_06_rbac.py` (6), `test_07_concurrency_and_cascades.py` (8), `test_08_workflow_depth.py` (8), `test_09_boundaries_and_overlaps.py` (8), `test_10_priority_and_invariants.py` (8)

One design note: literal timestamp assertions (e.g., `response_due_at == 2026-08-16T00:00:00Z`) are compared by parsed instant rather than raw string, because PRD §2.4 ("three fractional digits") leaves the surface format open while pinning the instant — this preserves the asserted values without failing format-faithful implementations.

## Step 7: Run Tests and Iterate — 2026-08-14T14:05:00.000Z

All 8 parallel rounds pass 86/86 with zero failures. Exit condition met.

## Summary

**Iterations run:** 2 (sweep 1: 6 deterministic failures in every round; sweep 2 after fixes: all 8 rounds clean, 86/86 × 8).

**Tests deleted:** none — every failing test's asserted rule traces verbatim to PRD; all failures were test-setup bugs.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`** (all STEP 2 test-bug fixes — setups issued requests a PRD-faithful implementation must reject, per PRD §3.1 "A Product is created with a unique business `product_code`"):

1. `/home/ubuntu/github/CodingPRD/tasks/task_1733_consumer_complaint_management_regulator/test_suite/test_04_validations.py::test_error_template_in_use_blocks_retire` — removed the duplicate `setup_reference_data("P-V8", ...)` preceding `setup_complaint("P-V8", ...)` (which internally re-creates the same reference data); template creation reordered after the single `setup_complaint` call.
2. `test_04_validations.py::test_error_template_mismatch_channel_or_category` — same duplicate-setup fix for `P-E6`; `create_category("C.E6B")` and template creation moved after `setup_complaint`.
3. `test_07_concurrency_and_cascades.py::test_occ_taxonomy_recode_stale_version_rejected` — same duplicate-setup fix for `P-X1`; `create_category("C.X1B")` moved after `setup_complaint`.
4. `test_07_concurrency_and_cascades.py::test_substantiated_rca_completion_cascades_product_posture_freeze` — added the missing `complete_rca` import (NameError; it is exported from `test_helpers` via `fixtures.py`).
5. `test_10_priority_and_invariants.py::test_referential_template_beats_constraint_rca_on_draft_response` — duplicate-setup fix for `WIR-DOM`; DRAFT template creation moved after `setup_complaint`.
6. `test_10_priority_and_invariants.py::test_template_not_active_single_failure_with_completed_rca` — duplicate-setup fix for `WIR-INTL`.

No assertions were weakened, no tests skipped, no scaffold-only rules removed.

**Fixes applied to `implementation/`:** none — the implementation was already PRD-faithful; all failures were caused by test setups violating PRD uniqueness constraints.

A repository-wide scan of all 10 test files confirmed no other test repeats the duplicate reference-data creation pattern (products, channels, or categories).

## Step 8: Finalize PRD — 2026-08-14T14:15:00.000Z

Task complete. PRD_FINALIZED.md written at `/home/ubuntu/github/CodingPRD/tasks/task_1733_consumer_complaint_management_regulator/workspace/PRD_FINALIZED.md`.

## Summary on exit

**Line counts / delta:** PRD.md 317 lines → PRD_FINALIZED.md 319 lines (+2 lines, +0.63%). Diff is a single inserted sentence (plus its separating blank line) at the end of §3.1.

**Changes (one total):**
- §3.1 — insert — after the TaxonomyCategory paragraph, added: "Uniqueness is enforced at creation across all three families: creating a Product, Channel, or TaxonomyCategory whose `product_code`, `channel_code`, or `category_code` is already registered to an existing record is rejected with `ERR_INVALID_REQUEST` (HTTP 400)." — impl: `workspace/implementation/routes_admin.py:61-62` (products), `:208-209` (channels), `:244-245` (categories).

**Per-item verification of the step_7_diff:**

1. `test_04::test_error_template_in_use_blocks_retire` — pre-fix failure caused by duplicate `setup_reference_data("P-V8", ...)`; impl rejected the second create with `ERR_INVALID_REQUEST` 400. Asserted rule (`ERR_TEMPLATE_IN_USE`, test_04:190-210) traces verbatim to PRD §3.9 and impl routes_admin.py:382-388. The duplicate-rejection error identifier was PRD-silent → covered by the §3.1 edit.
2. `test_04::test_error_template_mismatch_channel_or_category` — same duplicate-setup root cause (P-E6). Asserted `ERR_TEMPLATE_MISMATCH` traces verbatim to PRD §3.5 → same edit covers it.
3. `test_07::test_occ_taxonomy_recode_stale_version_rejected` — same root cause (P-X1). Asserted `ERR_STALE_VERSION` traces verbatim to PRD §2.7 → same edit covers it.
4. `test_07::test_substantiated_rca_completion_cascades_product_posture_freeze` — pure test-code bug (missing `complete_rca` import; NameError). `complete_rca` is defined at test_helpers/fixtures.py:244 and re-exported via `from .fixtures import *` (test_helpers/__init__.py:26). No PRD/impl behavior involved → no edit.
5. `test_10::test_referential_template_beats_constraint_rca_on_draft_response` — same duplicate-setup root cause (WIR-DOM); asserted ordering (template activeness before `ERR_RCA_REQUIRED`) traces to PRD §2.6 step 5 list order → same edit covers it.
6. `test_10::test_template_not_active_single_failure_with_completed_rca` — same root cause (WIR-INTL); asserted `ERR_TEMPLATE_NOT_ACTIVE` traces verbatim to PRD §3.5 → same edit covers it.

**Pre-edit search log (NO-NEW-MISMATCH RULE):**
- (a) Subject: rejection error/status when creating reference data with an already-registered business code.
- (b) Paths enumerated (grep over all impl files for `_by_code`/`_by_key` membership checks, `already exists`, and code-field assignments): routes_admin.py:55-73 (create_product), :201-217 (create_channel), :238-259 (create_category — noting its duplicate check at :244 fires before parent-code resolution at :246-251), :299-320 (create_template, template_key duplicate at :309-310). Confirmed no other path creates, registers, or mutates these codes (recode at routes_complaints.py:214-221 only resolves `new_category_code`; no PUT/PATCH endpoints exist for reference data).
- (c) Wording adjustments made before committing: (i) scoped to the three §3.1 families only — template_key duplicate rejection (routes_admin.py:310) was never exercised by any step_7 item, so per hard scope §3.9 was left untouched and the sentence makes no claim about templates; (ii) deliberately free of any pipeline-ordering claim, because the category create path checks duplicate before parent resolution, so wording asserting a §2.6 pipeline position would have mis-described that off-site path; (iii) error/status matches §5's existing `ERR_INVALID_REQUEST` → 400 mapping, so §5 and §2.6 needed no changes.

All other step_7-diff items required no PRD edit: five were pure fixture bugs whose asserted rules were already pinned verbatim by the PRD, and one was a test import bug with no behavioral content.

## Step 9: Complete PRD — 2026-08-14T14:25:00.000Z

PRD_COMPLETED.md is complete and intact. Final summary:

## Summary

**Source:** `PRD_FINALIZED.md` (319 lines, 48,817 chars) → **`PRD_COMPLETED.md`** (320 lines, 52,176 chars; **+3,359 chars**). 14 edited passages, no new sections.

**Counts:** 10 ambiguity-pins, 4 mismatch-revisions.

### Changes

- **§2.1** — revise — mismatch — RemediationApprover SoD narrowed to "approving or rejecting" (reversal has no self-approval guard; the original "barred from acting on decisions they drafted" covered reverse, which impl does not enforce) — `implementation/routes_remediation.py:168-179`
- **§2.2** — insert — ambiguity — `api_request_timestamp` pinned as stamped from the logical clock, not wall time — `implementation/response.py:13`
- **§2.2** — insert — ambiguity — unmatched route or unsupported method → `ERR_NOT_FOUND` (404); unexpected failure → `ERR_INTERNAL` (500) in the same envelope — `implementation/app.py:44-56`
- **§2.3** — insert — ambiguity — out-of-range `limit`/`offset` are clamped (not rejected); non-integer values → `ERR_INVALID_REQUEST`; `created_at` ties break by creation order; `has_more` = `offset + len(returned) < total_count` — `implementation/middleware.py:146-170`, `implementation/services.py:454-459`, `implementation/response.py:27`
- **§2.4** — insert — ambiguity — derived-field reconciliation (product `posture`/counters/`early_warning_active`; complaint `timeliness_score`/restitution ledgers) refreshes in place without bumping `version`/`updated_at`; `version` bumps only where §3 names it — `implementation/services.py:172-260` (no `touch` in any `recompute_*`)
- **§2.5** — insert — ambiguity — clock set accepts any valid instant; no forward-only constraint — `implementation/routes_admin.py:41-48`
- **§2.6 step 3** — insert — ambiguity — taxonomy-category and response-template creation evaluate request shape before body-code resolution (cross-reference to §3.1/§3.9) — `implementation/routes_admin.py:240-251, 301-310`
- **§2.6 step 4** — insert — ambiguity — malformed/non-object JSON body → `ERR_INVALID_REQUEST`; explicit null for optional fields treated as omitted; `rounding_rate_bps` when present must be an integer ≥ 0 — `implementation/middleware.py:63-123`, `implementation/routes_remediation.py:37-40`
- **§2.7** — revise — mismatch — replaced "a referral submission" with "a remediation-decision draft" in the version-bump examples (referral submission never bumps the complaint's `version`) — `implementation/routes_referrals.py:48-59`
- **§3.1** — insert — ambiguity — category retire has no from-state guard: re-retiring succeeds and bumps `version` again; creation order pinned as shape → duplicate-code (400) → `parent_category_code` resolution (404) — `implementation/routes_admin.py:286-292, 240-251`
- **§3.5** — insert — ambiguity — qa_fail requires the acting reviewer to hold an `OPEN` review on the complaint, otherwise `ERR_INVALID_STATE_TRANSITION`, evaluated after the SoD and complaint-state checks — `implementation/routes_complaints.py:286-292`
- **§3.6** — revise — mismatch — "as it always is for `NO_ACTION` and `CORRECTION`" replaced: the server does not require empty `line_items` for those types; supplied items feed the same floor-and-sum — `implementation/routes_remediation.py:44-67`
- **§3.6** — insert — ambiguity — `X-Manager-Authority: true` compared case-insensitively — `implementation/routes_remediation.py:125-126`
- **§3.7** — revise — mismatch — review-completion guard order pinned to impl order: outcome shape (400) → SoD (`ERR_SOD_SELF_REVIEW`) → `OPEN` state → ownership (`ERR_REVIEW_NOT_OWNED`); PRD had listed ownership first — `implementation/routes_reviews.py:71-84`
- **§3.9** — insert — ambiguity — template creation order (shape → code resolution 404 → duplicate `template_key` 400) and duplicate-key error `ERR_INVALID_REQUEST`; retire requires `ACTIVE`, otherwise `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_admin.py:301-320, 372-381`
- **§3.10** — insert — ambiguity — "latest RCA" defined as the most recently created RCA, counting only when `COMPLETED` with verdict `SUBSTANTIATED` (applied to both snapshot `substantiated_count` and `substantiated_count_90d`); trailing-90-day window pinned as inclusive of `received_at` exactly 90 days back — `implementation/services.py:163-169, 183-190`, `implementation/routes_admin.py:166-169`
- **§3.10** — revise — mismatch — posture recompute triggers: "every RCA completion" narrowed to SUBSTANTIATED completions (linked product only), and "every manual unfreeze" dropped (unfreeze sets `WATCH` directly without recomputing); also pinned unfreeze on non-FROZEN → `ERR_INVALID_STATE_TRANSITION` — `implementation/routes_rcas.py:99-103`, `implementation/routes_admin.py:94-106`
- **§4** — insert — ambiguity — `retired` list filter accepts case-insensitive `true`/`false`; any other value applies no filter — `implementation/routes_admin.py:276-281`

All other impl behaviors (62 endpoints' RBAC vs §4, state machines, OCC gates, restitution/timeliness/posture math, cascades, event stream, serializers) were verified as already uniquely pinned by PRD prose.
