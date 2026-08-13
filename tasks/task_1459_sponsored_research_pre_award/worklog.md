# Worklog — task_1459_sponsored_research_pre_award

## Step 2: Generate Scaffold — 2026-08-13T11:19:45.392Z

Step 2 complete. All three scaffold artifacts generated and lint-clean.

## Artifacts written

- `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/SCAFFOLD.yaml` (1541 lines) — §1.0–§1.7 only (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (1416 lines) — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/SCAFFOLD_CORNER_DESIGN.yaml` (2113 lines) — single top key `scaffold_corner_design`

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(52 endpoints, 13 entities, 26 §1.8 instances, 60 §1.9 instances, 883 calls scanned)

## Design summary

**Complexity profile:** compliance_audit (primary) + multi_party_negotiation (secondary); layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, rate_threshold_triggers; flat topology, cyclic state machines, segregation_of_duties role model, immediate consistency. Logical clock via `POST /pre-award/_clock/set_current_utc` with the mandatory `2026-08-01T00:00:00Z` default.

**Core mechanics (harder-than-expert calibration):**
- F&A engine: MTDC vs TDC base variants, PROVISIONAL vs FINAL rate-selection bases, per-line-then-sum rounding pin, first-$25k-per-subaward MTDC allowance with pinned (fiscal_year, created_at) processing order, sponsor rate caps via min() clamp with inclusive boundary.
- Cost-share algebra: pinned evaluation order for the circular-looking required-minimum → third-party 50%-credit → 25%-of-required cap chain.
- 13-entity graph with 12-state Proposal machine (revision cycle ROUTED→RETURNED→DRAFT, JIT amendment loop with AWARDED-state re-pin), ComplianceReview info-request/expiry cycles, NegotiationOffer supersede rounds.
- Two OCC rules (budget-finalize, offer-create) with 412 ERR_STALE_VERSION; two segregation-of-duties checks (route/approve, commit/approve).
- Three transitive cascades from distinct triggers (review disapproval depth-3, award acceptance depth-2, deadline sweep depth-3); deadline semantics fixed so ERR_INTERNAL_DEADLINE_PASSED and ERR_OPPORTUNITY_CLOSED are each reachable (sweep closes on sponsor deadline, submit gates on internal deadline).

**Difficulty design:** 26 instances — every one of the 9 rules has ≥2 (eight rules have 3), each with structured `setup_api_calls` replayed from empty DB, all numeric asserts pre-computed (e.g., MTDC indirect 7020000 vs TDC 9990000; rounding trap 2¢ vs 1¢; cost-share effective 2962500; enhanced risk 55 vs standard 40).

**Corner design:** 60 active instances across all nine claim-guide sections (entities 8, state_machines 10, calculations 5, validations 12, endpoints 4, errors 8, rbac 7, cross-cutting 5, consistency 1) plus 13 `excluded_because` stubs citing §1.8 instances; every error in the 35-code catalog has at least one trigger test.

Issues caught and fixed during generation: sponsor-vs-internal deadline sweep masking (reachability), FINAL-rate pin staleness post-award (added AWARDED→AWARDED re-approval transition), YAML flow-context quoting for `field?` inputs and `$.data[N]` captures, `$.data.total_count` captures replaced with prose asserts, and ComplianceReview.CANCELLED enum closure made explicit.

## Step 3: Copy INSTRUCTION.md — 2026-08-13T11:20:22.353573888Z

Copied ./INSTRUCTION.md to tasks/task_1459_sponsored_research_pre_award/workspace/INSTRUCTION.md.

## Step 4: Generate PRD — 2026-08-13T11:42:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/workspace/PRD.md` (311 lines, ~57 KB) from `SCAFFOLD.yaml`. The two forbidden design-index files were not opened, nor was any sibling task.

**Document structure:**
- §1 Introduction (2 paragraphs — OSP business context + segregation-of-duties/auditability angle)
- §2 ten subsections: 2.1 RBAC (all 7 roles, PI entity-backed vs 6 opaque identities translated), 2.2 response envelope (emitted byte-verbatim from `section-2.2-response-structure.md`), 2.3 pagination, 2.4 logical clock + internal deadline, 2.5 common resource properties (incl. SubmissionPackage's absent `updated_at`/`version`), 2.6 money/rounding discipline, 2.7 OCC (both rules, `expected_proposal_version`, `ERR_STALE_VERSION` 412, no race framing), 2.8 validation-order ladder mirroring scaffold priorities 1–10, 2.9 nested existence, 2.10 cascade consistency
- §3 nine subsections along the pre-award pipeline (intake/eligibility → rate agreements → drafting/budget → cost-share → routing/approval → compliance → subrecipient risk → submission/JIT/negotiation → handoff), with all calculations translated to precise prose (per-line round-half-up-then-sum, $25,000/2500000-cent MTDC subaward allowance consumed in `fiscal_year`-then-`created_at` order, third-party credit lesser-of rule in pinned order, risk-score weights/tiers incl. the $250,000 enhanced-variant surcharge, half-open window overlap with exactly-100.00 effort passing)
- §4 endpoint table: 52 rows, 4 columns; §5 error catalogue: 36 rows, 2 columns. No audit footer.

One note: the scaffold itself contains two differing sweep-threshold statements (state machine: `sponsor_deadline_at < now`; calculation: `internal_deadline_at < now`). Per the no-reinterpretation rule, both were projected faithfully in their natural homes (§3.1 and §2.4 respectively) without reconciliation.

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields + endpoint inputs/query params: 109 required, 109 present, 0 missing
- enum/state values (auxiliary check): 79 required, 79 present, 0 missing
- errors[].id in §2/§3 prose: 36 required, 36 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 ordered categories (scaffold priorities 1,2,3,4,5,5.5,6,7,8,9,10), 11 expressed in §2.8, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint capability + expected_proposal_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 34 checked (9 state machines incl. all self-loops, sweeps, and ANY_NON_TERMINAL branches), 34 fully expressed, 0 missing
- calculations[]: 5 checked (indirect_cost with MTDC/TDC/PROVISIONAL_BASIS/FINAL_BASIS variants, cost_share_requirement, subrecipient_risk_score standard/enhanced, pi_effort_capacity, internal_deadline), 5 fully expressed with constants, 0 missing
- validations[] conditions: 36 error_ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 52 checked, 52 expressed, 0 missing
- entities[].fields[] structured content: defaults/initials/nulls/types reconstructible from prose (incl. SubmissionPackage common_fields exception), 0 missing
- sibling-branch symmetry: 6 groups (3 approve-institutional forms, MTDC/TDC, PROVISIONAL_BASIS/FINAL_BASIS, standard/enhanced risk, accept/decline, JIT notice/response), all equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 648
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

(Verification note: an initial scan produced false "missing" results because the verbatim §2.2 JSON fences break naive backtick pairing; re-running against fence-stripped content — pairing even — confirmed true coverage.)

## Step 5: Generate Unit Tests — 2026-08-13T12:35:00.000Z

RESUME NOTE (orchestrator): prior run terminated mid-flight before this entry was written, but Step 5 artifacts were found complete on disk and validated — `test_helpers/` (9 modules, incl. factories/fixtures/test_users/assertions) and `test_suite/` (conftest.py + 12 test modules, 133 `Design:` tags across Difficulty/Corner queues) all pass `python3 -m py_compile`. Artifacts kept and reused; no regeneration.

## Step 6: Generate Implementation — 2026-08-13T12:35:00.000Z

RESUME NOTE (orchestrator): prior run terminated mid-flight before this entry was written, but Step 6 artifacts were found complete on disk and validated — `workspace/implementation/` contains app.py, db.py, errors.py, middleware.py, response.py, routes_core.py, routes_proposals.py, routes_reviews.py, routes_workflow.py, serializers.py, services.py, utils.py, requirements.txt, and a `bash -n`-clean start.sh (10 lines). All modules pass `python3 -m py_compile`. Artifacts kept and reused; no regeneration.

## Step 7: Run Tests and Iterate — 2026-08-13T12:55:00.000Z

All 8 rounds pass 133/133. Clean sweep.

## Summary

**Iterations run:** 2 (initial baseline + 1 fix-and-rerun).

**Tests deleted:** none.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/test_suite/test_02_budget_math.py` — added `get_success_data` to the `from test_helpers import (...)` import block. The test `test_line_add_on_locked_drops_to_draft` referenced the helper but it wasn't imported (NameError).
- `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/test_suite/test_12_concurrency_lifecycle.py` — fixed `_setup` in `TestOccOnFinalize` to re-fetch the proposal via `get_proposal(prop["id"])` after `add_budget_line(...)`. The line add increments the proposal's `version` per PRD §2.5/§3.3, so the previously-returned dict held a stale version=1 while the server was already at version=2, causing `ERR_STALE_VERSION` from the subsequent `finalize_budget(...)` OCC-guarded call. Both `test_first_finalize_advances_version` and `test_replayed_version_rejected_stale` now operate on the live version.

**Fixes applied to `implementation/`:** none.

All 8 parallel rounds of the per-test-server sweep now pass 133/133.

## Step 8: Finalize PRD — 2026-08-13T13:02:00.000Z

PRD_FINALIZED.md is produced at `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/workspace/PRD_FINALIZED.md`, byte-identical to PRD.md. Summary below.

## Line counts and delta

- PRD.md: 311 lines; PRD_FINALIZED.md: 311 lines; **0.0% delta** (zero edits).

## Changes

None. Both Step 7 diff items were pure test-fixture bugs over behavior the PRD already pins uniquely; per the method, no patch was made.

## Per-edit (candidate) pre-edit search log

**Candidate edit 1 — from `test_02_budget_math.py` import fix**
- (a) Subject: possible PRD silence around whatever `get_success_data` touches (response envelope `data` extraction on success).
- (b) Paths enumerated: `test_helpers/__init__.py:12` (re-export), `test_helpers/fixtures.py:8` (origin: `prd_bench_local_runner.testing`), `test_suite/test_02_budget_math.py:13,573`; cross-checked envelope shape against `implementation/response.py` and PRD §2.2.
- (c) Decision: no edit. The fix was a missing `import` in the test file only (NameError); the helper and the §2.2 success-envelope contract were already present and consistent. No behavioral choice was at stake, so there was nothing to pin.

**Candidate edit 2 — from `test_12_concurrency_lifecycle.py TestOccOnFinalize._setup` re-fetch fix**
- (a) Subject: whether a budget-line add/delete increments the parent proposal's `version` (and thereby trips `ERR_STALE_VERSION` on a subsequent OCC-guarded `finalize_budget` call).
- (b) Paths enumerated and read: `implementation/routes_proposals.py:253-292` (`add_budget_line`), `:322-337` (`delete_budget_line`), `:241-250` (`_line_mutation_side_effects` — unconditional `touch(p)` in all three eligible statuses DRAFT/BUDGET_LOCKED/JIT_REQUESTED), `:344-408` (`finalize_budget` — version check at `:349-354` placed after existence, before state checks), `implementation/db.py:48-52` (`touch` → `version += 1`); also grepped all other `touch(` callsites across `routes_core.py`, `routes_reviews.py`, `routes_workflow.py`, `services.py` to confirm the versioning discipline is uniform. PRD cross-refs: §2.5 line 89, §2.7 line 99, §2.8 item 4 (line 108), §2.10 line 125, §3.3 line 149 (*"Every line add or delete increments the proposal's `version`."*) and line 151 (OCC guard on finalization).
- (c) Decision: no edit. The PRD already pins this behavior unconditionally and verbatim at §3.3 line 149 (reinforced by §2.5/§2.10), and the OCC ordering at §2.8 item 4 matches `finalize_budget`'s check order exactly. The test failure was a stale client-side fixture dict, not a PRD ambiguity or impl/PRD mismatch. Any added wording would have been redundant and risked narrowing the unconditional "Every line add or delete" claim (e.g., by implying it applies only in certain statuses — it does not, per `_line_mutation_side_effects`), violating the no-new-mismatch rule.

## Step 9: Complete PRD — 2026-08-13T13:35:00.000Z

Done. `PRD_COMPLETED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_1459_sponsored_research_pre_award/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` 311 lines / 57,790 chars → `PRD_COMPLETED.md` 311 lines / 61,184 chars (char-delta +3,394; 22 paragraphs touched, no sections added or removed).

**Counts**: 6 mismatch-revisions, 19 ambiguity-pins (25 edits total; several paragraphs carry one pin each, all inline).

**Mismatch revisions:**
- §2.4 — revise — mismatch — intake-closure sweep keyed on `sponsor_deadline_at` (strictly before current time), not the internal deadline; exact-tie stays PUBLISHED — services.py:387
- §2.8 step 8 — revise — mismatch — `ERR_OPPORTUNITY_CLOSED` gate applies to approval from ROUTED/JIT_REQUESTED only; the AWARDED re-approval performs no opportunity check — routes_workflow.py:104-110
- §2.10 — revise — mismatch — carve-out: bare `compliance_posture` recomputation (review open / request-info / respond / approve / clock-driven expiry) refreshes neither `updated_at` nor `version`; only the disapproval cascade increments — routes_reviews.py:100,124,154,187,211; services.py:405
- §3.3 — revise — mismatch — SUBAWARD line ties to an existing subrecipient commitment of any status, not "a verified subrecipient plan" — routes_proposals.py:273-275
- §3.3 — revise — mismatch — `counts_toward_mtdc` allowance clause scoped to non-cost-share SUBAWARD lines; a cost-share SUBAWARD line reads true — services.py:314-320
- §2.6 — revise — mismatch — effort compared as exact decimals against 100.00 with no pre-rounding (was "compared at two-decimal precision") — services.py:132-142

**Ambiguity pins:**
- §2.2 — insert — ambiguity — `api_request_timestamp` generated from server wall clock, not the logical clock — utils.py:27
- §2.2 — insert — ambiguity — 204 deletion response carries no body (exception to the empty-object rule) — routes_proposals.py:337
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit` (1–100) and non-integer/negative `offset` rejected `ERR_INVALID_REQUEST` 400 — response.py:47-65
- §2.3 — insert — ambiguity — `created_at` ties broken by order of creation — routes_proposals.py:45
- §2.3 — insert — ambiguity — `has_more` = offset + items-returned < total_count — response.py:26
- §2.4 — insert — ambiguity — clock response `current_utc` echoes the submitted `to_iso8601` string — routes_core.py:36
- §2.4 — insert — ambiguity — logical-clock timestamps (`internal_deadline_at`, `submitted_at`, `jit_due_at`, `approved_until_at`, `handoff_at`) render at whole-second precision when integral, else 3 fractional digits — utils.py:36-41
- §2.5 — insert — ambiguity — `version` starts at 1 on creation for every versioned resource — db.py:43
- §2.6 — insert — ambiguity — percent figures serialize as JSON numbers, integral values without fractional part — utils.py:79-86
- §2.8 — insert — ambiguity — payload fields an endpoint does not define are ignored, not rejected — utils.py:102-115
- §3.1 — insert — ambiguity — negative `delinquent_report_count` is malformed (400) — routes_core.py:117-118
- §3.2 — insert — ambiguity — `rate_pct` outside (0, 100] is malformed (400) — routes_core.py:163-164
- §3.2 — insert — ambiguity — finalization rejected by the overlap check leaves the agreement PROVISIONAL — routes_core.py:198-202
- §3.2 — insert — ambiguity — among several covering agreements of the preferred status, earliest-created is selected — services.py:220,228
- §3.3 — insert — ambiguity — proposal creation with `pi_id` ≠ `X-User-ID` fails `ERR_INSUFFICIENT_PERMISSIONS` 403 — routes_proposals.py:75-78
- §3.3 — insert — ambiguity — PATCH: absent/null fields unchanged, unknown fields ignored, and a no-op edit still resumes RETURNED_FOR_REVISION→DRAFT and increments version — routes_proposals.py:174-206
- §3.4 — insert — ambiguity — pledging permitted against a proposal in any status; pledge creation and PLEDGED-withdrawal recompute totals without incrementing the proposal's version — routes_workflow.py:225-245,295-307
- §3.4 — insert — ambiguity — award-readiness adequacy run evaluates against final-basis totals and gates the handoff only; stored cost-share fields not rewritten — routes_reviews.py:479
- §3.6 — insert — ambiguity — negative `validity_days` override is malformed (400) — routes_reviews.py:174-175
- §3.7 — insert — ambiguity — subrecipient commitment attachable whatever the proposal's status; new commitment carries null `verified_risk_snapshot_score`/`monitoring_level` — routes_reviews.py:219-250
- §3.7 — insert — ambiguity — HIGH-risk acknowledgement gate keys on the org's registry (standard-variant) `risk_tier` — routes_reviews.py:274
- §3.8 — insert — ambiguity — negative `due_in_days` malformed (400); JIT response retains `jit_due_at` — routes_workflow.py:195-200,206-218
- §3.8 — insert — ambiguity — idempotent replay runs before state/opportunity/deadline gates and returns the original package with 201, side-effect-free — routes_workflow.py:145-147
- §3.8 — insert — ambiguity — `portal_confirmation_code` format `PC-` + 12 uppercase hex characters — routes_workflow.py:164

Notable confirmations (no change needed): the PRD's §3.1 sponsor-deadline sweep wording already matched impl (only §2.4 contradicted it); validation ordering in every route matches the §2.8 ladder; all cascade, rounding, allowance, risk-scoring, and gate-order prose matched impl exactly.
