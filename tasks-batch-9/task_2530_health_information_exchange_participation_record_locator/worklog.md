# Worklog — task_2530_health_information_exchange_participation_record_locator

## Step 1: Create task directory — 2026-09-03T06:08:10.617Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2530_health_information_exchange_participation_record_locator` and its `workspace/` subdirectory. Index 2530 was pre-assigned by the caller; no scan of ./tasks/ was performed and no other task directory was created.

## Step 2: Generate scaffold — 2026-09-03T07:47:52.425Z

All three artifacts are complete and lint-clean.

## Output
`/home/ubuntu/github/CodingPRD/tasks/task_2530_health_information_exchange_participation_record_locator/`
- `SCAFFOLD.yaml` — 3054 lines. `scenario` (verbatim), `domain_name: health-information-exchange-record-locator`, `api_prefix: /hie`, `response_envelope`, `complexity_profile`, **15 entities**, **11 state machines**, **3 concurrency rules** (OCC-only, 412), **7 calculations**, **38 ordered validations**, **58 endpoints**, **51 errors**, **5 roles** (each with `identity:`; `ParticipantAdmin`/`PublicHealthOfficer` are `entity_backed:Participant`). No `scaffold_*_design` keys.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1695 lines, single key, **9 rules × 2 = 18 instances** (`dual_variant_calc`, `combinatorial_formula`, `non_linear_state_machine`, `transitive_cascade`, `priority_pair_validation_conflict`, `boundary_precision_check`, `cross_entity_state_dependency`, `resource_temporal_overlap`, `compensating_invariant`).
- `SCAFFOLD_CORNER_DESIGN.yaml` — 3773 lines, single key, **76 instances across all 9 §1.9 sections** (55 with full `test_recipe`, 21 `excluded_because` stubs): Entities 12, State Machines 12, Calculations 14, Validations 14, Endpoints 8, Errors 6, RBAC 4, Cross-Cutting Complexity Layers 5, Consistency Model 1.

## Verification
`python3 skills/prd-bench-scaffold-generator/scaffold_lint.py tasks/task_2530_.../` verdict, verbatim:
```
  §1.5 endpoints declared:    58
  §1.1 entities declared:     15
  §1.8 instances scanned:     18
  §1.9 instances scanned:     55
  Calls scanned (§1.8+§1.9):  752

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
Also machine-checked: all 51 error ids are triggered somewhere in the two design files; every `excluded_because.difficulty_instance` resolves to a real §1.8 name; instance names unique across both files; no forbidden concurrency vocabulary; every §1.9 `section`/`claim_type` maps to a row of `references/claim-extraction-guide.md` (including per-algorithm rows for all six algorithm types in use and all three dual-variant rows). No sibling task directory was read.

## Design adjudications made in this pass
- **Subscription activation gate**: state machine accepted `{PASSED, WAIVED}` on the wrong profiles; rewritten to require a strictly `PASSED ADT_PUBLISHER` run, matching validation 21 and the §1.8 instance that depends on WAIVED being insufficient.
- **SoD anchors**: standardized on `MatchThresholdConfig.activated_by_user_id` (state machine had used `tuned_by_user_id`), and corrected three field descriptions that attributed PrivacyOfficer-only operations to HieAdmin.
- **`GET /hie/access-audit-entries[/{id}]`** was listed as PrivacyOfficer-exclusive in §1.7 while §1.5 also grants HieAdmin; moved to PrivacyOfficer's `shared_operations`. Likewise removed `GET /hie/participants` from HieAdmin's `exclusive_operations` (endpoint also grants PrivacyOfficer). Exclusive-op lists now agree with every endpoint `roles` list.
- **Zero-sample scorecard**: pinned the ambiguous branch — `count(S) == 0` reports `quality_score` null, `grade`/`provisional_grade` UNGRADED, penalty 0 and all components 0, while a non-empty S with `messages_received == 0` is graded via the `max(1, R)` guard.
- **Feed first-sample breach**: added a note that PROVISIONING→MONITORED continues to DEGRADED in the same request when the first sample already breaches `FEED_DEGRADED_REJECT_RATE`.
- **`DECLARE_DELINQUENT` before `due_date`** had no dedicated error; broadened `ERR_INVALID_STATE_TRANSITION` and validation 10 to cover preconditions without their own error id.
- Fixed a latent bug in the new RBAC steward instance: `match_score`'s candidate set excludes same-participant records, so the 0.7700 pair was split across two participants.

## Step 3: Copy shared files — 2026-09-03T07:47:52.425Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-03T08:04:02.852Z

PRD generation for task_2530 is complete.

## Output
`workspace/PRD.md` — **513 lines**, built with 10 sequential `cat >>` heredoc appends (no single giant Write).

## Section list
- `# Health Information Exchange Record Locator API — Product Requirements Document`
- `## 1. Introduction` (3 paragraphs)
- `## 2. Global Specifications & System-Wide Principles` — 11 subsections: 2.1 User and Role-Based Access Control · 2.2 API Response Structure (byte-verbatim from `section-2.2-response-structure.md`) · 2.3 Pagination · 2.4 Common Resource Properties · 2.5 The Logical Clock · 2.6 Optimistic Concurrency Control · 2.7 Path Resolution and Referential Integrity · 2.8 Numeric Precision · 2.9 Validation Precedence (all 38, numbered, each with error id + `applies_to` scope) · 2.10 Cascade Discipline · 2.11 Segregation of Duties and Audit Permanence
- `## 3. Business Logic & Workflows` — 9 subsections: 3.1 Participant Onboarding · 3.2 Conformance Testing · 3.3 Statewide Governance Generations (consent policy + match tuning) · 3.4 Contributing Patient Records and Resolving Identity · 3.5 Stewardship: Adjudication, Merge Cascades, Compensating Unlinks · 3.6 Patient Consent Directives and Their Precedence · 3.7 The Record Locator Query · 3.8 Break-the-Glass, Post-Hoc Review, Sanction Accrual · 3.9 Feed Quality, Notification and the Economics of Participation
- `## 4. Endpoint Definitions` — 4-column table
- `## 5. Error Code Catalogue` — 2-column table

## Coverage (mechanically verified against SCAFFOLD.yaml via `yaml.safe_load` + backtick-token diff)
- Endpoints: **58/58** exact (method, path) matches — 0 missing, 0 extra; **role assignments 0 mismatches** across all 58.
- Errors: **51/51** rows, **0 HTTP-status mismatches**.
- Entity fields: **156/156** present verbatim in backticks.
- Enum values: **101/101**. State-machine states: **40/40**.
- Body params 76/76, query params 39/39, computed-read outputs 15/15.

## Hard Contract reports
- **Contract 1 — Field-Name Coverage: PASS.** All 156 field names, 101 enum values, 40 states, 51 error ids, 76 body params, 39 query params and 15 computed-read outputs appear verbatim in backticks. Two gaps found and fixed during verification: `data_feed_id` (added to §3.9 sample-recording prose) and `WITHHELD` (three §3.7 withholding branches rewritten to "recorded with an `action` of `WITHHELD`").
- **Contract 2 — Rule Coverage: PASS.** All 38 validations with priority order and `applies_to` scopes (§2.9); 3 OCC rules plus the unlink operation that shares `expected_cluster_version` (§2.6); 12 state machines including the `BreakGlassAccess` two-axis `session_status` × `review_status` product and the `MatchLink` / `Participant` cycles; all 6 calculations rendered as prose with named constants and pinned evaluation/rounding order, including the scaffold's own two disambiguating worked examples (fee V=30001 → 49877 vs 49876; scorecard base 84.60 → grade B → penalty 1 → 83.60 → grade C); cascade ordering, version propagation, recount-not-adjust, membership and fiscal invariants (§2.10); segregation-of-duties and audit permanence (§2.11). No pseudocode, no fuzzy quantifiers.
- **Contract 3 — §3 Path Purity: PASS.** 1206 backticked tokens scanned in §3: 0 begin with `/`, 0 are bare HTTP methods, 0 combine method+path.

## Completeness confirmation
`wc -l` = 513. `tail -40` ends with the §5 table rows through `` | `ERR_PAYMENT_AMOUNT_MISMATCH` | 422 | `` — a complete final table row at a genuine section boundary, not mid-sentence. No Hard Contract report text leaked into PRD.md (it ends at §5).

Constraints honoured: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, grepped or referenced, and no sibling `task_*/` directory was read.

One deliberate omission worth flagging: the scaffold's `0.5300` probabilistic example match score was left out because the "reference weights" it depends on are not defined anywhere in the scaffold and so are not reconstructible; the variant difference is stated qualitatively instead.

**Orchestrator truncation check (per caller's guard):** independently verified — `wc -l` = 513, `tail -25` ends on the complete final error-catalogue row `| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |`, and `grep '^#'` shows all of §1–§5 present with §3.1–§3.9 intact. Not truncated; no regeneration needed.

## Step 6: Generate implementation — 2026-09-03T08:40:00.000Z

(Recorded before Step 5 because Step 6's subagent finished first; the two ran concurrently.)

Done. Everything verified on a fresh boot.

## Modules (30 files, 5,035 lines total)

Root — `workspace/implementation/`

| File | Lines |
|---|---|
| `app.py` | 82 |
| `db.py` | 192 |
| `errors.py` | 129 |
| `middleware.py` | 96 |
| `response.py` | 97 |
| `validate.py` | 191 |
| `start.sh` | 8 (chmod +x) |
| `requirements.txt` | 1 |
| `routes/records.py` | 353 |
| `routes/participants.py` | 283 |
| `routes/governance.py` | 228 |
| `routes/feeds.py` | 210 |
| `routes/breakglass.py` | 183 |
| `routes/invoices.py` | 183 |
| `routes/locator.py` | 178 |
| `routes/subscriptions.py` | 166 |
| `routes/conformance.py` | 162 |
| `routes/directives.py` | 146 |
| `routes/clock.py` | 18 |
| `services/clusters.py` | 194 |
| `services/consent.py` | 194 |
| `services/scorecard.py` | 148 |
| `services/repo.py` | 135 |
| `services/sanctions.py` | 109 |
| `services/fees.py` | 107 |
| `services/cascades.py` | 96 |
| `services/matching.py` | 93 |
| `services/counters.py` | 41 |
| `services/conformance.py` | 39 |
| `services/precision.py` | 39 |

## Coverage

- **Endpoints: 58/58.** A programmatic diff of Flask's `url_map` against the `method`/`path` pairs declared in `SCAFFOLD.yaml` reports `MISSING: none`, `EXTRA: none` (28 POST + 30 GET, including `POST /hie/_clock/set_current_utc`).
- **Errors: 51/51** in the `STATUS` map, and every one is reachable — a source scan for `"ERR_*"` literals found zero declared-but-never-raised codes.
- **Storage:** in-memory dicts only (15 tables on `db.Store`), zero seeded rows, no SQLite/file/tmp persistence. `__pycache__` dirs removed.

## Boot verification

`PORT=18531 bash start.sh` booted clean on the first try with no import or runtime errors, and I then ran a 64-assertion end-to-end smoke script against it covering every subsystem: **0 failures.** Highlights that pin down the numeric spec:

- Registration produced `provisional_monthly_fee_cents: 299877` for V = ceil(360012/12) = 30001 — exactly the PRD's worked fee example (250000 + 43313 + 6564), with `fee_tier: TIER_2`.
- Conformance at the floor: 190/200 → `pass_rate: 0.95`, `PASSED`.
- Scorecard: `base_quality_score 99.03`, grade `A`, `penalty_points 0`, 90-day window `2026-05-03 → 2026-08-01`.
- Two-participant identity matching auto-linked at score `1.0`, merged the clusters (`member_record_count 2`, `participant_count 2`), and `unlink` correctly restored the loser record to a fresh cluster with `prior_cluster_id` cleared.
- Consent: OPT_OUT directive → `DENIED_OPT_OUT` with two `WITHHELD` audit entries; break-glass citation flipped the same query to `PERMITTED_EMERGENCY` with 2 disclosed; closure recomputed disclosure counters; `UNJUSTIFIED` review awarded 6 sanction points onto the participant.
- Precedence checks all returned the right code/status: `ERR_SOD_CERTIFIER_IS_SIGNATORY` 403, `ERR_STALE_CLUSTER_VERSION` 412, `ERR_QUALITY_SAMPLE_INVALID` 422 (overlap), `ERR_INVOICE_PERIOD_OVERLAP` 409, `ERR_INVOICE_PERIOD_NOT_ELAPSED` 422, `ERR_PAYMENT_AMOUNT_MISMATCH` 422, `ERR_BREAK_GLASS_COOLDOWN_ACTIVE` 409, `ERR_JUSTIFICATION_TOO_SHORT` 422, `ERR_REVIEW_NOT_CLAIMED_BY_ACTOR` 403, `ERR_CONDUIT_ORG_TYPE_INVALID` 422, `ERR_PURPOSE_NOT_PERMITTED_FOR_ROLE` 403, plus pagination bounds → `ERR_INVALID_REQUEST` 400 and 401 on a missing role header.

Server killed; port 18531 free. Test blindness held throughout — `test_helpers/`, `test_suite/`, both `SCAFFOLD_*_DESIGN.yaml` files and all sibling `task_*/` dirs were never read. I also left the concurrent test-generation agent's own `app.py` processes untouched (I killed only by matching the listening port, never by process-name pattern).

**Orchestrator note on step ordering:** Steps 5 and 6 were launched in two consecutive assistant messages rather than one, so strict single-message concurrency was not achieved. Isolation was preserved by other means: Step 6's prompt carried an absolute prohibition on reading `test_helpers/`, `test_suite/`, and both design YAMLs, and Step 6's subagent explicitly confirmed on exit that it never read them. Step 5 was still reading its four large inputs when Step 6 started, so `test_suite/` content was not available to it in any case.

## Step 5: Generate unit tests — 2026-09-03T09:33:00.000Z

The suite is complete: 91 tests, all collected, all tagged, all citations verbatim.

## Files created

`test_helpers/` (Stage 1, 3391 lines total)
- `__init__.py` — 24
- `api_client.py` — 1089
- `api_errors.py` — 140
- `assertions.py` — 422
- `constants.py` — 130
- `factories.py` — 354
- `fixtures.py` — 596
- `test_users.py` — 89
- `types.py` — 547

`test_suite/` (Stage 2, 7019 lines total)
- `conftest.py` — 23
- Queue A (difficulty): `test_01_dual_variant_calculations.py` 276, `test_02_pinned_evaluation_order.py` 165, `test_03_non_linear_lifecycles.py` 228, `test_04_transitive_cascades.py` 385, `test_05_validation_precedence.py` 305, `test_06_boundaries.py` 316, `test_07_cross_entity_gates.py` 311, `test_08_temporal_overlap.py` 393, `test_09_compensating_invariants.py` 432
- Queue B (corner): `test_10_entities.py` 587, `test_11_state_machines.py` 388, `test_12_calculations.py` 511, `test_13_validations.py` 784, `test_14_endpoints.py` 512, `test_15_errors.py` 548, `test_16_rbac.py` 361, `test_17_complexity_layers.py` 386, `test_18_consistency_model.py` 131

## Tests per queue

- Queue A (Difficulty): **36 tests** covering all 18 live instances, >=2 each (audit: no instance below 2).
- Queue B (Corner): **55 tests**, exactly one per each of the 55 non-stub instances across all 9 sections (Entities 12, State Machines 8, Calculations 7, Validations 9, Endpoints 5, Errors 6, RBAC 4, Cross-Cutting Complexity Layers 3, Consistency Model 1). The 21 `excluded_because:` stubs were not translated.
- Total 91. A programmatic audit against both yaml files confirms every `Design:` tag resolves to a live instance and no live instance is uncovered; no tag points outside the indices.

## Verification run

- Citation checker over all 18 files: `checked 91 tests, 91 correctly tagged, 0 problems` (every `PRD n: "..."` quote survives a whitespace-normalized literal match against `workspace/PRD.md`; exactly one trailing `Design:` line per test).
- `pyflakes` clean on all test files (only the intentional re-export "unused import" notices in `test_suite/conftest.py` and `test_helpers/__init__.py`).
- `pytest --collect-only`: 91 tests collected, no import or fixture errors.

## SKIPPED design instances

**None.** Every live instance in both indices passed the PRD-first two-condition filter and was translated.

## Deviations from the literal design recipes (all PRD-driven, none weaken an assertion)

a. `SUBSTANCE_USE` -> `SUD` (the PRD's actual enum member).
b. Dropped `MatchThresholdConfig.cfgB2.scored_link_count == 1` — the PRD contradicts it.
c. Audit-entry `purpose_of_use` asserted on the `RecordLocatorQuery` row, which is where the PRD puts it.
d. Difficulty rule 7, instance 2 re-sequenced: §3.2 forbids submitting conformance results for an already-`CERTIFIED` participant.
e. `duplicate_component == 99.375` asserted with `abs=0.001` tolerance rather than exact equality.
f. `ADT_SEMANTICS` -> `VOCABULARY` (non-PRD failure category in the recipe).
g. Calculations#6 right-hand family name "Achebe" -> "Acheson", so the strong-identifier floor conjunction genuinely fails and the pinned 0.6000/`REJECTED` outcome holds.

A previously noted eighth deviation (relative instead of absolute feed `version` values in Endpoints#2) was withdrawn: §2.10's "its own `version` incremented by exactly 1" makes the absolute ladder derivable, so `version` 1->2->3->4 is asserted outright.

## Step 7: Run tests and iterate — 2026-09-03T09:47:30.000Z

All 8 rounds are green: 91/91 in every round, zero failures, zero errors.

## Iterations run
2 (sweep 1 → 17 deterministic failures across all 8 rounds; sweep 2 after fixes → 8/8 clean). No flakiness was observed in either sweep — the same set failed in all 8 rounds of iteration 1.

## Tests deleted
None. Every failing test's rule traced verbatim to PRD prose; all 17 resolved as either a test mis-translation (STEP 2) or an implementation defect (STEP 3). One hallucinated *assertion* was replaced rather than the test deleted (partial-coverage handling, STEP 1c).

## Fixes applied to `test_helpers/`
None — no fixture/factory/header bug was implicated. The three defective artifacts all lived in `test_suite/`.

## Fixes applied to `test_suite/`
- `test_05_validation_precedence.py`, `TestConformanceGateOutranksDelinquentFee._certified_on_a_waived_publisher_run` — submitted `failure_categories=["ADT_SEMANTICS"]`, a value outside PRD §3.2's declared domain (`SECURITY`, `PATIENT_ID_INTEGRITY`, `VOCABULARY`, `TRANSPORT`, `PAYLOAD_STRUCTURE`); the PRD-faithful server correctly returned `ERR_INVALID_REQUEST`. Changed to `VOCABULARY` (still non-critical, so the run's `FAILED`/waiver path is unchanged).
- `test_06_boundaries.py`, `TestAutoLinkThresholdIsInclusive` — asserted `link["merged_away_cluster_id"] == right_record["cluster_id"]`, but PRD §3.4 says the auto-link merge repoints the incoming record's `cluster_id` at the *winner* and stores the loser in `prior_cluster_id`; the contribution response is post-merge. Assertion now uses `right_record["prior_cluster_id"]` as the loser (and additionally pins `right_record["cluster_id"] == left_record["cluster_id"]`).
- `test_06_boundaries.py`, `TestQualityWindowLowerBoundIsExclusive` — `ONE_SECOND_PAST_THE_EDGE_SAMPLE` window `[04-03T00:00:01, 05-03T00:00:01)` overlapped the class's `EDGE_SAMPLE` `[04-03, 05-03)`, so PRD §3.7's "a window overlapping any existing sample on the same feed" correctly rejected it with `ERR_QUALITY_SAMPLE_INVALID`. Retimed the two windows to be adjacent-not-overlapping (`INSIDE_SAMPLE` starts `05-03T00:00:01`, the past-the-edge sample occupies `[05-03T00:00:00, 05-03T00:00:01)`), preserving the exact boundary being probed (`period_end` one second past `window_start`) and all arithmetic, which depends only on the counts.
- `test_16_rbac.py`, `TestTheTunerMayNotStewardItsOwnLinks` — asserted `match_state == "PENDING_MATCH_REVIEW"`, an enum member that appears nowhere in PRD.md (PRD §3.4 declares exactly `CLUSTERED`, `QUARANTINED`, `WITHDRAWN_FROM_INDEX`, and PENDING_REVIEW routing "mutates **no** cluster membership at all"). Replaced with the PRD-verbatim `CLUSTERED`; the surrounding SoD assertions (`ERR_SOD_STEWARD_IS_TUNER`, link `PENDING_REVIEW` → `LINKED`, merge) were kept intact.

## Fixes applied to `implementation/`
- `services/scorecard.py`, `compute()` / `apply_to_participant()` — the scorecard read emitted the final grade under the key `quality_grade`. PRD §3.9 names the scorecard's own field `grade` ("Fourth derive the final `grade` from `quality_score`" … "`grade` and `provisional_grade` are both `UNGRADED`" … "the participant row itself carries the latest `quality_score` and `quality_grade`"). Renamed the scorecard key to `grade`; `apply_to_participant` still writes the participant row's `quality_grade` from it. This single fix cleared 13 of the 17 failures.
- `routes/participants.py`, `read_participant()` / `list_participants()` — `sanction_points_active` was only recomputed on write, so clock-only decay was invisible. PRD §3.8: "Because the window is anchored on the logical clock, moving the clock alone can change the total." Reads now recompute the live sum (no version bump, since no row data conceptually changes).
- `routes/participants.py`, `transition_onboarding()` `REINSTATE` branch — the "strictly below twelve" gate read the stale stored total; now evaluates the recomputed clock-anchored sum, for consistency with the same PRD sentence.

**Orchestrator verification of the sweep artifacts (per the known Step-7 failure mode where a clean sweep is claimed but no results files exist):** independently confirmed on disk — `results.1.json` … `results.8.json` all present (timestamped 09:45, ~31.9 KB each) and each parses to `{'passed': 91, 'failed': 0, 'total': 91, 'errors': 0}`. The clean 8-round sweep is real.

## Step 8: Finalize PRD — 2026-09-03T09:56:00.000Z

Done. `PRD_FINALIZED.md` is a two-line patch of `PRD.md`.

## Line counts
- `PRD.md`: 513 lines; `PRD_FINALIZED.md`: 513 lines (0.0% line delta; 2 lines revised in place, no lines added/removed, file intact through the §5 error catalogue).

## Changes
- **§3.8, "The active sanction total and its decay"** — *revise* — appended one sentence pinning that the individual participant fetch and the participant list re-evaluate `sanction_points_active` against the current clock and store the result on the row before reporting it (so clock-only decay is visible without a write), and that this read-time re-evaluation refreshes neither `updated_at` nor `version` — `implementation/routes/participants.py:252-261, 264-270`; `implementation/services/sanctions.py:25-43`.
- **§3.9, "Suspension, reinstatement and termination"** — *revise* — pinned that the reinstatement "strictly below twelve" gate evaluates the clock-anchored sum recomputed at request time, not the stored total left by a previous write — `implementation/routes/participants.py:185-194`.

## Per-edit pre-edit search log

**Edit 1 — subject: `sanction_points_active` (who computes it, when, and its version effects)**
(b) Enumerated/read: `grep -rn "sanction" implementation/**/*.py` (full hit list); `services/sanctions.py` (`active_points`, `recompute` — mutates row, no commit; `refresh_and_maybe_suspend` — snapshot→recompute→cascade→`commit`, so version bumps only when data changed); `routes/participants.py` `read_participant`, `list_participants`, `transition_onboarding` REINSTATE, `new_participant_fields` (born 0), `read_scorecard` (does **not** touch sanctions); `routes/breakglass.py:123-156` (only write-path caller); `db.py` `snapshot`/`commit`/`touch` semantics; confirmed no other participant-returning endpoint (`CERTIFY`, `SUSPEND`, invoices, feeds) recomputes the sum.
(c) Adjustment: narrowed the claim from "any read of a participant" to exactly "the two participant reads — the individual fetch and the participant list", because `GET /participants/{id}/scorecard` and every write endpoint that returns or touches a participant report the stored total without recomputing. Also scoped strictly to `sanction_points_active` — `quality_score`/`quality_grade` and `outstanding_balance_cents` are *not* refreshed on read, so no general "derived counters refresh on read" wording. Added the explicit "not a mutation" clause so the sentence cannot be read as contradicting the existing §3.8 line "The participant's `version` increments by 1 whenever the sanction sum changes" (which remains true of the review-decision write path).

**Edit 2 — subject: the REINSTATE sanction gate**
(b) Enumerated/read: `routes/participants.py:185-194` (gate order: state → `sanctions.recompute(...) >= 12` → delinquent-invoice check) and `:226-231` (the REINSTATE effect set), `services/sanctions.py:41-57`, `SANCTION_SUSPENSION_THRESHOLD = 12`, plus the parallel inclusive-at-twelve automatic-suspension comparison in `refresh_and_maybe_suspend`, and §2.9 rule 10 (gate has no dedicated code → `ERR_INVALID_STATE_TRANSITION`, which impl raises).
(c) Adjustment: phrased as "re-evaluated … at the moment of the request" rather than "recomputed and stored", to stay agnostic about whether the gate's recomputation persists on a *failed* request (impl mutates the in-memory row but never commits, and the value is unobservable because reads recompute anyway). Deliberately did **not** pin the relative order of the sanction gate vs. the `ERR_PARTICIPATION_FEE_DELINQUENT` check — no Step 7 item exercised it, and asserting an order would be a new claim.

## Step 7 items that needed no PRD edit
The four `test_suite/` fixes were all test-side defects against prose the PRD already determines: the out-of-domain `failure_categories` member (§3.2 domain + §2.9 rule 6), the auto-link loser identity (§3.4 "every patient record whose `cluster_id` was the loser has its `prior_cluster_id` set to the loser and its `cluster_id` set to the winner"), the overlapping sample window (§3.9 half-open `[period_start, period_end)` + "a window overlapping any existing sample"; impl's `start < other_end and other_start < end` permits adjacency), and the hallucinated `PENDING_MATCH_REVIEW` match state (§3.4 declares exactly three). The scorecard `grade` rename was an implementation defect against PRD §3.9, which already names the field `grade` — the impl now conforms, so the prose stays verbatim.

## Step 9: Complete PRD — 2026-09-03T10:22:00.000Z

**Orchestrator decision (recorded per the AUTONOMY directive):** Step 9 was run as **three sequential, file-partitioned passes** over a single shared `PRD_COMPLETED.md` rather than as one monolithic subagent. Rationale: the implementation is 30 files / 5,035 lines, and a single-pass agent asked to walk all of it exhaustively tends to `cp` the source PRD and then run out of working context before making edits — producing a byte-identical output file that looks finished but never actually scanned. Pass A created the file from `PRD_FINALIZED.md`; passes B and C edited it in place with an explicit prohibition on recreating or overwriting it, plus hand-off notes carrying each pass's cross-partition findings forward.

Partition: **A** = `app.py`, `db.py`, `errors.py`, `middleware.py`, `response.py`, `validate.py`, `routes/{clock,participants,conformance,governance}.py`, `services/{conformance,repo,precision}.py`. **B** = `routes/{records,directives,locator,breakglass}.py`, `services/{clusters,matching,consent,cascades,counters,sanctions}.py`. **C** = `routes/{feeds,subscriptions,invoices}.py`, `services/{scorecard,fees}.py`. Every implementation file was covered exactly once.

### Aggregate result
`PRD_FINALIZED.md` 513 lines / 112,028 chars → `PRD_COMPLETED.md` 513 lines / **133,836 chars** (**+21,808 chars**, +19.5%; 57 changed-line groups). All edits are in-paragraph inserts/revisions — no lines added or removed, no new sections. **67 pins total: 48 ambiguity-pins, 19 mismatch-revisions.**

### Pass A — core/envelope/onboarding (+10,069 chars; 18 ambiguity, 6 mismatch)
- **§2.1 (L17)** — insert — ambiguity — a whitespace-only `X-User-Role` is also `ERR_UNAUTHENTICATED`, both headers are stripped before use, and a missing `X-User-ID` is read as the empty string rather than being an error — `middleware.py:53-61`
- **§2.1 (L19)** — insert — ambiguity — an unrecognized `action`/`decision`/`outcome` value falls through to the schema layer as `ERR_INVALID_REQUEST`, never `ERR_ACTION_NOT_PERMITTED_FOR_ROLE` — `middleware.py:64-73`
- **§2.1 (L31)** — insert — ambiguity — `EMERGENCY` is in the purpose enum but in no role's permitted set (so always 403), while an out-of-domain purpose is a schema fault — `middleware.py:24-36,86-96`
- **§2.2 (L54)** — insert — ambiguity — `api_request_id` is `req_` plus exactly sixteen upper-case-alphanumeric characters — `db.py:65-70`
- **§2.2 (L55)** — insert — **mismatch** — `api_request_timestamp` is read from the host's real clock, not the logical clock — `db.py:96-98`, `response.py:17`
- **§2.3 (L84)** — insert — ambiguity — `offset` has no maximum; an empty `limit`/`offset`/filter is treated as absent; pagination is validated before filtering; `created_at` ties are broken by row-creation order everywhere in the document; filters are exact string compares whose out-of-domain values match nothing rather than faulting — `response.py:70-97`, `db.py:186-188`, `participants.py:267-280`
- **§2.4 (L88)** — insert — ambiguity — `updated_at` equals `created_at` on a fresh row; unfilled fields are present-and-null, not omitted — `db.py:147-159,191-192`
- **§2.5 (L96)** — revise — **mismatch** — "nothing reads wall-clock time" narrowed to exempt `api_request_timestamp`; clock accepts any instant including backwards, returns 200, and sub-millisecond precision is kept for comparisons but truncated when rendered — `db.py:74-98`, `routes/clock.py:12-18`
- **§2.6 (L102)** — revise — **mismatch** — unrecognized body fields are ignored, so a version field on an endpoint that does not declare one is harmless rather than fatal — `validate.py:13-25`
- **§2.8 (L118)** — insert — **mismatch** — the four-decimal regime governs computed figures only; a tuning generation's declared bounds, weights and partial-credit factor are stored/compared/echoed verbatim with no rounding or decimal-place check — `governance.py:152-183`, `precision.py:35-39`
- **§2.9 rule 6 (L135)** — insert — ambiguity — the exact accepted ISO-8601-UTC grammar (optional seconds/fraction, `Z`/`+00:00`/`+0000`, either case) vs. the strict `YYYY-MM-DD` date grammar; string/integer type rejections; absent-or-empty body reads as `{}` while non-object JSON faults; explicit `null` counts as absent — `db.py:15-131`, `validate.py:13-153`
- **§2.10 (L173)** — insert — ambiguity — a cascade advances a visited row only when a non-meta field actually changed (a no-op recount leaves `updated_at`/`version` alone), whereas the path-addressed row of a transition advances unconditionally — `db.py:169-183`, `participants.py:248` *(later narrowed by pass B — clusters advance unconditionally)*
- **§3.1 (L189)** — insert — ambiguity — `agreement_version`, `agreement_signed_at`, `agreement_executed_by_user_id`, `certified_by_user_id`, `certified_at`, `suspension_reason` all null at registration — `participants.py:89-94`
- **§3.1 (L193)** — insert — ambiguity — the self-identity requirement on submit/resume/withdraw is a transition precondition, so a mismatch is `ERR_INVALID_STATE_TRANSITION`, not `ERR_PARTICIPANT_SCOPE_VIOLATION` — `participants.py:158-160,179-181,198-200`
- **§3.1 (L197)** — insert — ambiguity — the `REMEDIATE` reason is mandatory but not persisted; `suspension_reason` untouched — `participants.py:146-148,216-220`
- **§3.1 (L199)** — insert — ambiguity — withdrawal's forced failure writes only `status`/`failure_categories`, in ascending `created_at`, bumping each run's `version`; leaves `pass_rate`, `critical_failure`, `consecutive_failed_attempts`, `remediation_count` alone; takes no `reason` — `participants.py:237-245`
- **§3.2 (L205)** — insert — ambiguity — booked run's initial nulls/empty list/false flag, the participant `version` bump, and that booking imposes no onboarding-status gate at all — `conformance.py:41-71`
- **§3.2 (L207)** — insert — ambiguity — non-`RUNNING` run and non-`CONFORMANCE_TESTING` participant both give `ERR_INVALID_STATE_TRANSITION`; `PASSED`/`WAIVED` gives `ERR_TERMINAL_STATE` first — `conformance.py:83-89`
- **§3.2 (L211)** — insert — ambiguity — the remediation trigger does not reset `consecutive_failed_attempts`, and the three-failure test is a floor — `conformance.py:105-115`
- **§3.2 (L213)** — insert — ambiguity — waiver bumps the participant's `version`, has no onboarding gate, and the critical/non-`FAILED` refusals are `ERR_INVALID_STATE_TRANSITION` (or `ERR_TERMINAL_STATE`) — `conformance.py:127-140`
- **§3.3 (L221)** — revise — **mismatch** — `policy_version` uniqueness is not enforced by the server; `sensitive_categories_segmented` is optional and defaults to `[]` — `governance.py:66-69`
- **§3.3 (L225)** — revise — **mismatch** — `config_label` uniqueness not enforced; both bounds are only range-checked over the closed 0–1 interval at schema time, with "above zero" and "strictly below" deferred to the admissibility gate; no four-decimal check — `governance.py:151-168`
- **§3.9 (L388)** — insert — ambiguity — the reinstatement sanction gate runs first and reports `ERR_INVALID_STATE_TRANSITION`, ahead of the delinquency gate — `participants.py:185-194`
- **§3.9 (L390)** — insert — ambiguity — the termination `reason` is stored on the participant as `suspension_reason` — `participants.py:232-234`
- **§5 (L459)** — insert — ambiguity — undefined path → `ERR_INVALID_REQUEST` at 404, undefined method → 405, server fault → 500; trailing slashes are not distinguishing — `app.py:24,46-67`

Pass A note: `errors.py` matches the §5 status table exactly — no discrepancies.

### Pass B — identity/consent/locator/break-glass (+7,903 chars; 16 ambiguity, 11 mismatch)
Mismatch revisions:
- **§2.10** — revise — mismatch — the blanket "a cascade advances a visited row only when a non-meta field changed" was false for clusters; narrowed to the dependent rows that use the conditional path, with clusters called out as advancing unconditionally on merge/unmerge/link-routing/steward-decision/directive writes, and only participant termination's recount conditional — `services/clusters.py:147,150,179,182,194` vs `:189`, `services/cascades.py:87`
- **§2.9 rule 14** — revise — mismatch — `ERR_CLUSTER_MERGED_AWAY` is also raised by a `CONFIRM` steward decision; endpoint added to the list — `routes/records.py:235`
- **§3.4 AUTO_LINKED bullet** — revise — mismatch — `merged_away_cluster_id` stays null in the *same-cluster* degenerate case (not "when the incoming record had no cluster"); "both clusters increment version" narrowed to the two *distinct* clusters, unconditional; added that the record's throwaway minted cluster is always the first merge's loser, so an auto-linked contribution answers at `version` 2 with `prior_cluster_id` set — `services/clusters.py:123-151`
- **§3.4 PENDING_REVIEW bullet** — revise — mismatch — one recount+bump when both records share a cluster — `routes/records.py:184-186`
- **§3.5 ¶1** — revise — mismatch — "version on both touched clusters" → two increments for distinct clusters, one for a shared cluster — `routes/records.py:257-267`
- **§3.5 rejection** — revise — mismatch — `pending_review_link_count` falls out of a recount, not a decrement; "Both clusters" → each distinct cluster — `services/clusters.py:192-194`
- **§3.5 unlink** — revise — mismatch — only one cluster advances when `merged_away_cluster_id` was null (pass A's flag confirmed) — `services/clusters.py:154-183`
- **§3.7 step 4** — revise — mismatch — the four emergency conditions are not tested together: the three row-local ones sit at their §2.9 position, the cluster-coverage one is deferred past the active-generation gate and skipped entirely on a `NO_MATCH` — `routes/locator.py:78-90`, `services/consent.py:146-160`
- **§3.7 step 6** — revise — mismatch — `withheld_categories` is the union of `sensitive_category_hit` over *withheld* members (outcome-keyed, not reason-keyed) — `services/consent.py:172-176`
- **§3.8 closure** — revise — mismatch — a not-open session is refused with `ERR_TERMINAL_STATE`; `ERR_BREAK_GLASS_SESSION_NOT_OPEN` is left to the wrong-clinician case — `routes/breakglass.py:85-90`
- **§3.8 sanction cascade** — revise — mismatch — the participant advances exactly once per request when any of its own fields changed; a `JUSTIFIED` decision leaving the sum unmoved does not advance it — `services/sanctions.py:46-57`

Ambiguity pins:
- **§3.4 ¶2** — insert — record and its minted cluster are both still at `version` 1 unless a later link moves them — `routes/records.py:65-81,131-132`
- **§3.4 candidate selection** — insert — candidate set assembled once before any routing — `routes/records.py:134-150`
- **§3.4 per-field agreement** — insert — `field_agreement_map` stores agreements rounded half up to 4dp — `services/matching.py:90-93`
- **§3.4** — insert — each link advances `scored_link_count` and the generation's `updated_at`/`version` — `routes/records.py:176-177`
- **§3.4 recount trigger list** — revise — added `PENDING_REVIEW`, steward `REJECTED`, and directive record/revoke — `routes/records.py:184,257,265`, `routes/directives.py:93,119`
- **§3.5 step 2** — insert — degenerate same-cluster confirm has no loser; steps 3-4 no-op — `services/clusters.py:123-127`
- **§3.5 step 3** — insert — re-pointing covers all statuses; >2 ACTIVE rows in a triple all supersede, survivor names the runner-up — `services/clusters.py:44-72`
- **§3.5 step 4** — insert — the re-pointed subscription must itself be `PENDING_ACTIVATION`/`ACTIVE` to contest — `services/clusters.py:100-101`
- **§3.5 reopen** — insert — non-ACTIVE cluster yields `ERR_INVALID_STATE_TRANSITION`, and reopen is exempt from the steward-vs-tuner separation — `routes/records.py:217-226,237`
- **§3.6 recording** — insert — later-`effective_from` incumbent survives unnamed; several qualifying incumbents all supersede with `supersedes_directive_id` naming the last by `created_at`; policy `directive_count` counts rows of every status and advances the policy row — `routes/directives.py:74-97`, `services/counters.py:28-34`
- **§3.6 revocation** — insert — the policy row is untouched — `routes/directives.py:113-120`
- **§3.7 step 1** — insert — a `NO_MATCH` query leaves `governing_policy_id`/`governing_directive_id` null while still reporting `top_candidate_score` — `services/consent.py:136-147`
- **§3.8 ¶1** — insert — `cluster_id` resolves before `invoking_participant_id` — `routes/breakglass.py:39-40`
- **§3.8 cooldown** — revise — the window survives closure as well as expiry; no `session_status` releases it — `services/sanctions.py:73-88`
- **§3.8 review claim** — insert — the already-claimed check precedes the state test; self-claim and same-officer re-claim both give `ERR_INVALID_STATE_TRANSITION` — `routes/breakglass.py:105-115`
- **§3.8 last ¶** — insert — both session reads run lazy expiry, the list over every row before filtering — `routes/breakglass.py:163,171-173`

### Pass C — feeds/subscriptions/fees (+3,788 chars; 14 ambiguity, 2 mismatch)
- **§3.9 Provisioning a feed** — insert — ambiguity — provisioning has no onboarding-status gate beyond delinquency/version; any state incl. terminal — `routes/feeds.py:34-46`
- **§3.9 Provisioning a feed** — revise — ambiguity — the scorecard re-run fires on every provisioning, not only when an incumbent was retired — `routes/feeds.py:76`
- **§3.9 Recording a measurement window** — insert — ambiguity — `messages_rejected` > `messages_received` is `ERR_INVALID_REQUEST`, not a coherence failure — `routes/feeds.py:89`
- **§3.9 Recording a measurement window** — insert — ambiguity — a `RETIRED` feed answers `ERR_TERMINAL_STATE` ahead of the three coherence checks; any other status accepts, and a `SUSPENDED` feed banks the sample with no status change — `routes/feeds.py:95-96,133-144`
- **§3.9 Recording a measurement window** — revise — ambiguity — overlap is the half-open test (adjacency accepted) and is scoped to the same feed only — `routes/feeds.py:102-108`
- **§3.9 Feed suspend/restore** — insert — ambiguity — feeds readable individually + per-participant list filterable by `feed_type`/`status`; samples reachable only as the feed's unfiltered list — `routes/feeds.py:190-210`
- **§3.9 Scorecard components** — insert — ambiguity — the three ratio components carry no rounding; §2.8's two-place regime covers only the average/base/final scores, and the blend consumes unrounded values — `services/scorecard.py:103-105,122-124`
- **§3.9 Scorecard read** — revise — ambiguity — the read is pure: never written back (unlike §3.8 sanctions), advances no `updated_at`/`version` — `routes/participants.py:288`, `services/scorecard.py:69`
- **§3.9 Subscription creation** — revise — ambiguity — `event_types` stored verbatim (no dedupe/sort); non-`https://` URL is `ERR_INVALID_REQUEST` — `routes/subscriptions.py:33-36`
- **§3.9 Subscription creation** — revise — **mismatch** — the `ACTIVE`-cluster check applies to *any* supplied `cluster_id` and runs before both coherence rules, so `ERR_CLUSTER_MERGED_AWAY` wins over `ERR_SUBSCRIPTION_SCOPE_MISMATCH` — `routes/subscriptions.py:41-52`
- **§3.9 Subscription creation** — insert — ambiguity — creation touches the participant not at all; `active_subscription_count` counts only `ACTIVE` rows — `routes/subscriptions.py:54-68`, `services/counters.py:7-16`
- **§3.9 Subscription lifecycle** — revise — ambiguity — `REACTIVATE` re-checks neither the publisher run nor delinquency and preserves `activating_conformance_test_id` — `routes/subscriptions.py:102-129`
- **§3.9 Fee variants** — insert — ambiguity — a `PROVISIONAL` assessment still captures the live `quality_grade` in `quality_grade_snapshot`; registration stores that variant's `total_cents` as `provisional_monthly_fee_cents` — `services/fees.py:74-80`, `routes/participants.py:100`
- **§3.9 Fee variants** — revise — ambiguity — `RECONCILED` applies neither the 90-day window nor the six-sample cap — `services/fees.py:83-98`
- **§3.9 Issuing invoices** — revise — **mismatch** — the invoice row carries every computed field *except* `fee_tier`, which is participant-level only — `routes/invoices.py:70-90`
- **§3.9 Payment** — insert — ambiguity — scope is compared against the looked-up invoice's `participant_id`, so an unresolvable id falls through to `ERR_INVOICE_NOT_FOUND` (behind body schema faults) rather than a scope violation — `routes/invoices.py:99-105`

Pass C also re-executed `services/fees.py` and `services/scorecard.py` to confirm §3.9's worked examples still hold: 30,001 units → `TIER_1` 43,313 + `TIER_2` 6,564 = `volume_fee_cents` 49,877 (49,876 if summed-then-rounded), and base 84.60 → provisional `B` → 1 penalty → 83.60 → final `C`. Multipliers, base fee, caps and rates all match the prose. Pass C found no §3.9 `version` overclaim needing narrowing: the feed/subscription rows moved by the suspension cascade carry no `version` claim in the prose, and every `version` claim §3.9 does make is about a path-addressed row that impl `touch()`es unconditionally.

### Orchestrator verification
- `PRD_COMPLETED.md` is **not** byte-identical to its source: 513 lines, 133,836 chars vs `PRD_FINALIZED.md`'s 112,028, with 57 changed-line groups — the scan demonstrably ran in all three passes.
- File is untruncated: 28 headings (§1–§5 with §2.1–§2.11 and §3.1–§3.9 all intact) and the tail ends on the complete final error row `| ERR_PAYMENT_AMOUNT_MISMATCH | 422 |`.
- No line was added or removed by any pass — every edit is an in-paragraph insert/revision, so §4's endpoint table and §5's error catalogue are structurally untouched.
- `find` over `workspace/implementation/`, `test_suite/` and `test_helpers/` confirms **zero** files modified after the 09:45 clean sweep, so Steps 8 and 9 were documentation-only and the 8×91/91 green result still describes the shipped artifacts.

## Pipeline complete
All nine steps finished. Final artifacts: `SCAFFOLD.yaml`, `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`, `worklog.md`, `test_helpers/` (9 files, 3,391 lines), `test_suite/` (19 files, 7,019 lines, 91 tests), and `workspace/` with `INSTRUCTION.md`, `PRD.md`, `PRD_FINALIZED.md`, `PRD_COMPLETED.md`, `implementation/` (30 files, 5,035 lines) and `results.1.json`–`results.8.json` at 91/91.
