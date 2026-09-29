## Step 1: Create task directory — 2026-08-29T00:00:00.000Z

Created `tasks/task_2167_teacher_evaluation_tenure/` and `tasks/task_2167_teacher_evaluation_tenure/workspace/` (index derived from highest existing task_2166).

## Step 2: Generate scaffold — 2026-08-29T04:46:00.000Z

All three artifacts are generated and lint-clean.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2167_teacher_evaluation_tenure/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_2167_teacher_evaluation_tenure/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_2167_teacher_evaluation_tenure/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Design summary

**Profile** — Expert+: `compliance_audit` × `multi_party_negotiation`, flat topology, cyclic state machines, `segregation_of_duties` role model, immediate consistency. Layers: optimistic concurrency, cascading side effects, dual-variant calculation, rate/threshold triggers.

**Surface** — 13 entities, 51 endpoints, 35 error codes, 11 state machines, 9 calculations, 22 ordered validations, 5 roles, 3 OCC rules. `api_prefix: "/"` (flat root collections); logical clock defaults to `2026-08-01T00:00:00Z` per spec.

**Core mechanics** (all arithmetic executed in Python before being written as literals):
- Dual variants on *different* entity domains — `cycle_composite_score` PROVISIONAL 3.15 vs FINAL 2.62 on the same rows (FINAL pads missing required observations with a 1.00 floor); `evaluator_calibration_drift` ROLLING 0.55 vs ANCHOR 0.10 (certification consults ROLLING only).
- Combinatorial modes (b) and (c): per-domain rounding pinned before summation (3.42 vs the forbidden 3.41), and an evidence adjustment keyed on the *pre*-adjustment band while the stored rating comes from the *post*-adjustment score (2.55 → −0.10 → 2.45 DEVELOPING).
- Non-linearity on three entities: Observation `SCORED→SUBMITTED→RETURNED→SCORED`, EvaluationCycle's independent `status` × `dispute_state` axes, Evaluator `CERTIFIED→SUSPENDED→CERTIFIED`.
- Two cascades from different triggers — appeal REMANDED at depth 4 (appeal → cycle revert → plan VOIDED → educator hold/years), calibration FAIL at depth 3 (suspension → observation voids → cycle bubbles back to SCHEDULING).
- Two conserved quantities: school stipend cents and the evidence-artifact ledger, each with an exact compensating action.
- Two interval semantics on different resources: half-open evaluator window (adjacency legal) vs buffered educator formal-spacing on start instants (strict `<`, 9 days rejected / 10 accepted).

**Coverage** — §1.8: 9 rule_ids, 23 instances (≥2 each). §1.9: 42 instances across all nine claim-extraction sections, including 6 `excluded_because:` stubs.

**Verification run** (verbatim):
```
Coverage
  §1.5 endpoints declared:    51
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     32
  Calls scanned (§1.8+§1.9):  769

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Additional scripted checks passed: 65/65 instance names unique across both design files; 0 unresolved `grounds:` references; all `excluded_because.difficulty_instance` targets exist and carry no `test_recipe`; every one of the 35 error codes is exercised by at least one design instance; zero forbidden concurrency vocabulary; neither design key appears inside `SCAFFOLD.yaml`.

One scaffold correction made during the §1.9 audit: `ERR_RUBRIC_INCOMPLETE` (originally validation priority 18) was unreachable — an observation with fewer than four domains is still `CONDUCTED` and is caught by the higher-priority state check — so the error and its validation row were removed rather than left as a dead code.

The hard constraint held: no sibling `task_*/` directory was listed, read, or searched; only the skill's own `SKILL.md`, `references/claim-extraction-guide.md`, `scaffold_lint.py`, and the `api_prefix` line plus one endpoint listing from the skill's `examples/` directory were consulted.

## Step 3: Copy shared files — 2026-08-29T04:46:10.000Z

Copied `./INSTRUCTION.md` to `tasks/task_2167_teacher_evaluation_tenure/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-29T04:56:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2167_teacher_evaluation_tenure/workspace/PRD.md` — **422 lines**, written incrementally (7 append operations), ending at §5 with no audit footer.

**Structure**: §1 Introduction (3 paragraphs) · §2 with 11 subsections (2.1 RBAC, 2.2 verbatim response structure, 2.3 Pagination, 2.4 Identity/Versioning, 2.5 Bound Policy Row, 2.6 Precision, 2.7 Guarded Writes, 2.8 Screening Order, 2.9 Path Resolution, 2.10 Ledger Invariants, 2.11 Segregation of Duties & Logical Clock) · §3 with 9 domain-derived workflow subsections · §4 endpoint table (51 rows, 4 columns) · §5 error table (35 rows, 2 columns).

The two design-index files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced.

```
Field coverage check:
- entities[].fields: 108 required, 108 present, 0 missing
- endpoints[].request_body: 67 required, 67 present, 0 missing
- endpoints[].query_params: 18 required, 18 present, 0 missing
- endpoints[].output report keys: 11 required, 11 present, 0 missing
(two passes run; pass 1 found `observation_id` missing, repaired in §3.4; pass 2 clean)
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 22 checked, 22 expressed in prose, 0 missing
  (rendered as an explicit numbered evaluation order in §2.8, with each rule's
   applies_to set enumerated: "guards exactly six operations", etc.)
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed
  (expected_observation_version/ERR_STALE_OBSERVATION_VERSION/412,
   expected_cycle_version/ERR_STALE_CYCLE_VERSION/412,
   expected_plan_version/ERR_STALE_PLAN_VERSION/412 — all non-optional,
   framed purely as stale-version, no "simultaneous"/"race" wording)
- state_machines[].transitions: 53 checked across 11 machines, 53 fully expressed, 0 missing
  (incl. the Observation SCORED→SUBMITTED→RETURNED→SCORED revision loop, the
   EvaluationCycle status/dispute_state dual dimension, the
   CERTIFIED→SUSPENDED→CERTIFIED calibration cycle and its observation-void cascade)
- calculations[]: 9 checked, 9 fully expressed, 0 missing
  (pinned per-domain-then-sum rounding order, PROVISIONAL vs FINAL variants,
   ROLLING vs ANCHOR drift, pinned pre-band/post-band evidence adjustment —
   all in prose, no operator syntax, no fuzzy words)
- validations[] conditions: 22 checked, 22 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 26 checked, 26 expressed, 0 missing
- entities[].fields[] structured content: 108 checked, 108 reconstructible, 0 missing
  (every default, enum member set, initial value and null-before-X semantics stated)
- sibling-branch symmetry: 5 groups checked (appeal UPHELD/MODIFIED/REMANDED;
  grievance SUSTAIN/DENY/WITHDRAW; plan SUCCESS/FAIL-level-1/FAIL-level-2;
  evaluator six certification edges; observation void from six from-states),
  5 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 849
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Also verified: all 35 error IDs and all 5 role names appear in §2/§3 prose; every state value across all 11 machines and every enum member appears verbatim in backticks; §2.2 matches the canonical source byte-for-byte.

Orchestrator verification: 422 lines, §1–§5 all present, file ends at the §5 error table (no truncation).

## Step 6: Generate implementation — 2026-08-29T05:20:00.000Z

Implementation complete and verified.

## What was built

`/home/ubuntu/github/CodingPRD/tasks/task_2167_teacher_evaluation_tenure/workspace/implementation/` — Python + Flask, in-memory only (plain dicts in `store.py`), no seeding at startup, split across 14 modules:

- `start.sh` — guarded `pip install` (only when `flask` is missing) + `exec python3 app.py`; binds `0.0.0.0:$PORT` (default 10000). Cold boot to first response ≈ 0.75 s.
- `app.py` (registration, error handlers, per-request lock), `store.py` (logical clock, records, decimals), `errors.py` (35-error catalogue), `response.py` (envelope + pagination), `auth.py`, `validation.py`, `calc.py` (9 calculation rules), `services.py` (derived state, ledgers, cascades, serializers), and 6 route modules.

All **51 declared endpoints** are registered — verified programmatically against the scaffold endpoint table (0 missing, 0 extra).

## Verification

Three end-to-end smoke suites (~150 assertions) all pass, including every worked example in the PRD:
- pinned per-domain rounding: 3/2/4/3 unannounced formal → **3.42** (not 3.41)
- PROVISIONAL vs FINAL: oc 3.2475 → **3.15**; padded oc 2.3738 → **2.62**
- growth reliability: 3.2@50 + 2.4@30 → **2.5200**
- evidence penalty: pre 2.55 with 1 artifact → **2.45 / DEVELOPING**
- rolling vs anchor drift: 1.00 then 0.10 → rolling **0.55** (uncertified), anchor 0.10
- service years: 2023-08-02 @ 2026-08-01 → **3**
- stipend ledger commit/release, suspension cascade + `SCORING→SCHEDULING` bubble, plan escalation to `NON_RENEWED`, appeal `MODIFIED`/`REMANDED` cascades, grievance flow, tenure SoD, distribution report + outlier flag.

## Judgement calls worth flagging

1. **Rubric scoring is not ownership-guarded.** PRD §2.1 says an evaluator may "rubric-score … only those observations whose `evaluator_id` equals their own", but §2.8 step 5 says the ownership check "guards exactly six operations" — a list that excludes rubric scoring — and the scaffold's `validations[priority: 5].applies_to` agrees. I followed the two concurring sources.
2. **Three entities have no state error in the catalogue** (CalibrationReview, GrowthMeasure, EvidenceArtifact). For their *own* invalid-state transitions (re-deciding a decided review, certifying a non-`REPORTED` measure, withdrawing a withdrawn artifact) I return `ERR_INVALID_REQUEST` (400). Parent guards still use `ERR_OBSERVATION_STATE_INVALID` / `ERR_CYCLE_STATE_INVALID` as specified.
3. **Grievance filing checks `ERR_APPEAL_NOT_EXHAUSTED` before the cycle `dispute_state` check**, so that filing against a `FILED`/`UNDER_REVIEW` appeal yields the error PRD §3.8 explicitly names for all four non-`UPHELD` statuses.
4. **`finalize` does not enforce `completed_formal_count >= 1`** — PRD §3.6 and the scaffold state machine list only the pending-observation condition for that transition (the validations table's `applies_to` is broader).
5. **Report `school_id` is not existence-checked** (query params, like list filters, are not covered by §2.8's "path and body" existence rule).
6. `created_at` comes from the logical clock as PRD §2.4 requires, so ties are common; all ordering uses `(created_at, insertion_seq)` to keep "created_at ASC" stable.
7. Deciding an appeal compares `X-User-ID` to `panelist_evaluator_id` → `ERR_NOT_RESOURCE_OWNER`, but only when that field is set, so a `FILED` appeal still returns `ERR_APPEAL_STATE_INVALID`.

## Step 5: Generate unit tests — 2026-08-29T05:24:00.000Z

Test infrastructure and suite are complete and verified.

## What was generated

**`test_helpers/`** (9 modules, ~1,900 lines) — written one file at a time:
- `types.py` — 13 entity TypedDicts (all carry `id`/`created_at`/`updated_at`/`version`), 20 status/enum classes, `DOMAIN_ORDER`
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (51 endpoints)
- `api_errors.py` — 35-member `ApiErrorId` enum + HTTP status map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions plus the two ledger invariants (`assert_stipend_ledger`, `assert_evidence_ledger`) and precision checkers (2- vs 4-decimal, integer cents)
- `factories.py`, `constants.py`, `test_users.py` (per-instance builders `make_evaluator_headers` / `make_teacher_headers` / `make_appeal_panelist_headers` for the three entity-backed roles, plus the two distinct HrAdmin operator identities the tenure SoD rule needs)
- `fixtures.py` — tiered composites: `setup_district`, `setup_cycle`, `add_observation(stop_at=…)`, `setup_submitted_cycle`, `setup_finalized_cycle`, `setup_ineffective_cycle_with_plan`, `setup_appeal_under_review`, `setup_upheld_appeal`, plus clock/calibration/suspension drivers

**`test_suite/`** — `conftest.py` + 10 domain-named files, **78 tests**, built incrementally per file.

## Coverage (mechanically verified)

A checker script parses every test docstring, resolves its `Design:` tag against the two yamls, and greps each quoted citation against a whitespace-normalised `PRD.md`. Result: **ALL OK** — all 23 difficulty instances have ≥2 tests, all 32 non-stub corner instances have ≥1 test, every test has exactly one valid tag, and every citation is verbatim (no tag points at an `excluded_because` stub; all 9 stubs' cross-references resolve).

## Judgement calls worth flagging

- **One design-index assertion dropped as non-derivable.** `Corner/calculations/informal_observation_capped…` asserts `observation_component == 3.5000` under a policy with `required_informal_count: 0`. PRD §3.5 says only the earliest `required_informal_count` informals score the cycle — zero of them — so a PRD-only implementer uniquely derives `null`. The instance is still covered (cap 3.50, the four contributions, stipend 5000, budget 5000/95000, both completed counts); only that one value is not asserted.
- **`passed_calibration_count` never asserted.** The design asserts `== 3` and `== 1` on paths where PRD states the increment only for the two transitions *into* `CERTIFIED`; a faithful reader could omit it on a non-certifying PASS. Skipped per the Silence-pattern rule; `consecutive_failed_calibrations` is asserted only where PRD names the reset explicitly.
- Precedence tests were built so the two conflicting conditions are genuinely both violated (e.g. thin-budget school + partly-scored observation), with a sibling test proving the pre-empted check does fire on its own — so a passing precedence test can't be vacuous.

No file under `workspace/implementation/` was read or listed.

## Step 7: Test and iterate to green — 2026-08-29T05:32:00.000Z

All background tasks are done and the sweep is clean.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, no early exit).

- **Sweep 1:** 64/78 in all 8 rounds — 14 failures, identical in every round (deterministic, not flaky).
- **Sweep 2:** **78/78 in all 8 rounds.**

**Root cause (single upstream `test_helpers` bug, exactly the triage-hint pattern):** all 14 failures reported the same setup error — `HTTP 412: ERR_STALE_OBSERVATION_VERSION` — masquerading as 14 independent implementation bugs across access control, scheduling, composite calculation, disputes, tenure and reporting.

`add_observation()` in `test_helpers/fixtures.py` captured the observation's `version` from the `conduct` response, then attached `artifacts` evidence artifacts, then opened the guarded rubric-score chain with that pre-attach version. PRD §3.4 states attaching "increases the owning observation's `evidence_count` by 1", and PRD §2.4 states a resource's `version` "increases by exactly 1 on every mutation of that resource, whether the mutation was requested directly or arrived as a cascade" — so the observation's version legitimately moves on attach, and the fixture's cached value was stale by the time it was used. Only fixtures passing `artifacts > 0` were affected, which is exactly the 14-test set.

This was a STEP 2 test-helper fix, not an implementation bug: the implementation's §2.7 guard was correct and was not touched.

**Tests deleted:** none. Every failing test survived STEP 1a (PRD verbatim coverage) and STEP 1b (unique derivability); the fault was entirely in the fixture's precondition construction.

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py`, `add_observation()` — re-read the observation's current `version` (via the existing `observation_version()` helper) before calling `score_all_domains()` when artifacts were attached, instead of reusing the stale `conducted["version"]`. Falls back to `conducted["version"]` when no artifacts were attached, preserving the original no-intervening-read chaining path that other tests exercise.

**Fixes applied to `implementation/`:** none. No implementation check was removed, weakened, or added.

**Verification notes:** the 14 tests were confirmed green individually against a manually started server before the full sweep, and the final sweep produced `results.1.json` … `results.8.json` all reading `78 / 78`. A non-isolated single-server run showed 3 unrelated `ERR_DUPLICATE_EMPLOYEE_NUMBER` collisions from fixed employee numbers, which is expected only without `--isolation per-test-server` and does not occur under the benchmark's actual run mode.

Orchestrator verification: all 8 `results.{1..8}.json` present in `workspace/implementation/`, each reading `78 / 78`.

## Step 8: Finalize PRD — 2026-08-29T05:36:00.000Z

`PRD_FINALIZED.md` is written. Two edits, both tracing to the single Step 7 item.

## Line counts
- `PRD.md`: 422 lines — `PRD_FINALIZED.md`: 422 lines — **0.00% delta** (2 lines revised in place, no lines added or removed).

## Changes
- **§3.4 (Rubric Scoring, the Revision Loop, and Evidence — evidence attach)** — *revise* — the side-effect enumeration for attaching an evidence artifact now states explicitly that bumping `evidence_count` is a mutation of the observation and therefore increments that observation's `version` by 1 under §2.4, with the client-facing consequence that a version cached before the attach is stale for the next guarded rubric-score write — `implementation/routes_observations.py:242-246` (`observation["evidence_count"] += 1; touch(observation); … touch(cycle)`).
- **§3.4 (evidence withdrawal)** — *revise* — the compensating-action enumeration likewise now names the observation's `version` increment alongside the `evidence_count` decrement and the cycle's `version` increment — `implementation/routes_observations.py:280-284` (`touch(artifact); observation["evidence_count"] -= 1; touch(observation); … touch(cycle)`).

## Rationale
The Step 7 root cause (`HTTP 412: ERR_STALE_OBSERVATION_VERSION` in `add_observation()`) was a fixture bug, but it exposed a genuine PRD ambiguity: §3.4's attach sentence enumerated side effects and named the *cycle's* version increment while omitting the *observation's*, which reads as exhaustive and contradicts §2.4's general rule. A fresh implementer could reasonably land on either behavior. The impl bumps it; the PRD now says so. No implementation behavior was invented — every clause added is directly exhibited by the code.

## Per-edit pre-edit search log

**Edit 1 — attach**
- (a) Subject: which resources' `version` moves (and which counters change) when an evidence artifact is attached.
- (b) Paths enumerated / read: `routes_observations.py:220-247` (`attach_artifact`, the Step 7 site); `routes_observations.py:261-286` (`withdraw_artifact`, the compensating path); `services.py:80` (`recompute_cycle_evidence` — mutates fields, never calls `touch`); `store.py:110` (`touch` — the single `updated_at` + `version += 1` primitive, confirming uniform semantics); a full `grep -n "touch(" *.py` sweep over all 45 callsites to confirm no other path describes itself through these two sentences; and the neighbouring observation-version movers that the sentence must not over-claim about — `routes_observations.py:161-164` (conduct), `:187-202` (rubric score), `:312-317` (submit), `:340-344` (return), `:359` (accept), `:383-390` (void).
- (c) Wording adjustment: scoped the new clause strictly to the attach operation ("*that* observation's `version`") rather than any general statement about `evidence_count` or about observation-version movement. Anchored the increment to §2.4 rather than declaring a new independent rule, and left the cycle-version clause verbatim.

**Edit 2 — withdrawal**
- (a) Subject: same — the observation's `version` on the compensating withdrawal path. Forced by Edit 1: leaving the parallel sentence untouched would read as *excluding* an observation-version bump.
- (b) Paths enumerated / read: `routes_observations.py:261-286` (`withdraw_artifact`); `routes_observations.py:220-247` (attach, for symmetry); `services.py:80` (`recompute_cycle_evidence`); `routes_observations.py:383-390` (void — described by §3.5, not this sentence).
- (c) Wording adjustment: used "likewise increments that observation's `version` by 1" to bind the claim to withdrawal alone. The artifact's own `version` bump was deliberately left unstated, since §2.4's general rule already covers it.

## Step 9: Complete PRD — 2026-08-29T05:44:00.000Z

All 26 edits landed cleanly as in-paragraph inserts/revisions.

## Summary

**Files** — source `PRD_FINALIZED.md` (422 lines, 83,077 chars) → `PRD_COMPLETED.md` (422 lines, 88,069 chars). Char delta **+4,992**; 26 lines revised, 0 lines added/removed, no new sections or paragraphs.

**Counts** — ambiguity-pins: **21**, mismatch-revisions: **5**.

### Changes

- §2.1 — revise — mismatch — dropped "rubric-score" from the evaluator ownership sentence; impl enforces no ownership on rubric scoring (`routes_observations.py:332-343`)
- §2.3 — insert — ambiguity — list ordering ties on equal `created_at` broken by creation sequence (`store.py:384-389`)
- §2.5 — insert — ambiguity — remaining policy integers non-negative; decimal constants unbounded (`routes_config.py:16-44`)
- §2.8 step 5 — revise — mismatch — ownership guards **seven** ops, not six; adds deciding an appeal, excludes rubric scoring (`routes_disputes.py:283-285`)
- §3.1 — revise — mismatch — school `code` is not district-unique/enforced (`routes_config.py:81-95`)
- §3.2 — insert — ambiguity — calibration review's `sequence_index` is null until resolution (`routes_config.py:248`)
- §3.2 — insert — ambiguity — re-deciding a decided review → `ERR_INVALID_REQUEST` 400 (`routes_config.py:276-277`)
- §3.2 — insert — ambiguity — PASS/FAIL counters and evaluator `version` bump on every resolution (`routes_config.py:295-299,321`)
- §3.2 — insert — ambiguity — suspension cascade refreshes cycle evidence in place; cycle `version` moves only on bubble-down (`services.py:434-446`)
- §3.3 — insert — ambiguity — cycle `status` not consulted when scheduling, only `dispute_state` (`routes_observations.py:228-239`)
- §3.4 — insert — ambiguity — a superseded rubric row's own `version` increments (`routes_observations.py:348-351`)
- §3.4 — insert — ambiguity — artifact attach gated on ownership alone, no observation/cycle state gate (`routes_observations.py:384-411`, `services.py:254-259`)
- §3.4 — insert — ambiguity — withdrawing an already-`WITHDRAWN` artifact → `ERR_INVALID_REQUEST` 400 (`routes_observations.py:437-442`)
- §3.5 — revise — mismatch — every void refreshes evidence + completed counts; only a money-holding void recomputes `observation_component` and bumps cycle `version` (`routes_observations.py:541-555`)
- §3.6 — revise — mismatch — `index_value` decimal precision is not enforced; growth reporting is not gated on cycle status (`routes_growth.py:16-45`, `validation.py:497-513`)
- §3.6 — insert — ambiguity — certifying a non-`REPORTED` measure → `ERR_INVALID_REQUEST` 400 (`routes_growth.py:68-72`)
- §3.6 — insert — ambiguity — closure blocked by live dispute posture yields `ERR_CYCLE_STATE_INVALID` 409 (`routes_cycles.py:156-157`)
- §3.8 — insert — ambiguity — appeal filing also requires `dispute_state` `NONE`; at most one appeal per cycle (`routes_disputes.py:202-203`)
- §3.8 — insert — ambiguity — `adjusted_composite` stored raw on the appeal, rounded half-up to 2dp onto the cycle (`routes_disputes.py:293-299`)
- §3.8 — insert — ambiguity — `REMANDED` reversion leaves `observation_component`/`growth_component` standing (`services.py:402-412`)
- §3.8 — insert — ambiguity — grievance filing requires cycle `dispute_state` `APPEAL_RESOLVED` (`routes_disputes.py:321-323`)
- §3.8 — insert — ambiguity — role/outcome mismatch on grievance decision → `ERR_UNAUTHORIZED` 403 (`routes_disputes.py:366-369`)
- §3.8 — insert — ambiguity — `RATING_VACATED` on a non-`FINALIZED` cycle skips the reversion and only voids plans (`routes_disputes.py:390-394`)
- §3.9 — insert — ambiguity — `last_composite_rating` is stored (not read-derived) and bumps educator `version` only on an actual change (`services.py:369-376`)
- §3.9 — insert — ambiguity — an educator with no cycle has no bound policy and is never eligible → `ERR_TENURE_NOT_ELIGIBLE` (`routes_config.py:171-181`)
- §3.9 — insert — ambiguity — `NON_RENEW` with any other `last_composite_rating`, null included → `ERR_TENURE_STATE_INVALID` 409 (`routes_config.py:164-167`)

Notable non-change: §3.5's "recomputed … on every submit, return, accept and void" was left as written — accept and money-less voids do recompute, they just cannot change the counted set, so the general sentence stays true and the void paragraph now carries the precise version/component rule.

Orchestrator verification: PRD.md / PRD_FINALIZED.md / PRD_COMPLETED.md all 422 lines, all five sections intact in PRD_COMPLETED.md.
