# Worklog — task_2759_content_moderation_operations

## Step 1: Create task directory — 2026-09-04T17:23:49.806Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate scaffold — 2026-09-04T19:15:00.000Z

Subagent summary (verbatim):

All three scaffold artifacts are complete and lint-clean.

## Output files
`/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/`
- `SCAFFOLD.yaml` — 137,129 bytes
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 161,264 bytes
- `SCAFFOLD_CORNER_DESIGN.yaml` — 339,687 bytes

File split honored: `scaffold_difficulty_design:` / `scaffold_corner_design:` each appear only as the single top-level key of their own file and never inside `SCAFFOLD.yaml`. The scenario is byte-verbatim in `SCAFFOLD.yaml`'s `scenario:` key. No sibling task directory was read at any point.

## Counts
- §1.0–§1.7: 11 entities, 48 endpoints, 9 state machines, 12 calculations, 2 OCC concurrency rules (412, checked last at priority 70), 48 ordered validations, 61 errors, 6 roles. `api_prefix: /moderation`; profile: entity_topology graph, state_machine_shape cyclic, role_model segregation_of_duties, consistency immediate, layers = rate_threshold_triggers / cascading_side_effects / dual_variant_calculation / optimistic_concurrency / selector_policy / version_pinning_on_approval.
- §1.8: **9 rules / 23 instances**.
- §1.9: **9 sections / 94 instances** — 73 with full `test_recipe` chains + 21 `excluded_because` stubs. Per section: entities 11, state_machines 18, calculations 14, validations 10, endpoints 5, errors 22, rbac 6, cross_cutting_complexity_layers 7, consistency_model 1.
- Every one of the 61 declared error ids is referenced by at least one §1.8/§1.9 instance (0 uncovered). All 94 §1.9 names are unique across the §1.8 ∪ §1.9 union; all 21 stubs cite an existing §1.8 instance name and carry no `test_recipe`; all instances carry `grounds` + `claim_type`, and every grounds reference resolves to a declared §1.1–§1.7 element (verified mechanically).

## Lint verdict (verbatim)
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2759_content_moderation_operations/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2759_content_moderation_operations/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2759_content_moderation_operations/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    48
  §1.1 entities declared:     11
  §1.8 instances scanned:     23
  §1.9 instances scanned:     73
  Calls scanned (§1.8+§1.9):  1353

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Design adjudications
1. **Unreachable reviewer state fixed.** `Reviewer PENDING_RETRAINING -> ACTIVE` required the granted version to be in `pending_retraining_version_ids`, but an accuracy-gate demotion adds nothing to that list, so a gate-demoted reviewer could never recover. Added the "or `pending_retraining_version_ids` is already empty" clause, making a re-affirming grant the sanctioned way back.
2. **Activation cascade made consistently conditional.** Cascade step 3 (case `requires_recertified_review` flagging) was unconditional while step 2 (decertification) was gated on `requires_recertification == true`; step 3 and the activate endpoint's `side_effects` string were rewritten so both are gated, which is what makes the `version_pinning_on_approval` corner instance well-defined.
3. **Layer taxonomy adjudication.** The guide's layer table lists `conditional_feature_flags` but this scaffold declares `selector_policy` and `version_pinning_on_approval` instead, so the cross-cutting section uses only the scaffold's own declared layers as `claim_type` values (`optimistic_concurrency` x2, `rate_threshold_triggers`, `selector_policy`, `version_pinning_on_approval`, plus `cascading_side_effects` / `dual_variant_calculation` stubs).
4. **Validation-priority citations corrected**: the endpoint-role check is priority 2, not 10 (fixed in one grounds list and one assert that claimed "role check at priority 10").
5. **Enum/name corrections in my own design text**: audit verdict `DISAGREE` -> `DISAGREE_MATERIAL` (declared enum is AGREE / DISAGREE_MINOR / DISAGREE_MATERIAL), and `calculations.signal_routing_disposition` -> the declared `routing_disposition`.
6. **Duplication avoided by construction**: shape/pattern rows already probed by §1.8 (case cycle, ContentItem parallel dimensions, activation cascade, overturn compensation, weighted scoring, both dual-variant calcs, the five validation-pattern rows) are `excluded_because` stubs, and the corner instances deliberately pick different entities for the same rows (AuditSample SAMPLED->AUDITED->DISPUTED->AUDITED for `cyclic`, PolicyCategory for `bubble_up`, PolicyVersion revise for the BACKTESTING->DRAFT loop).
7. **OCC negatives are genuine stale views**, never bare literals: the case OCC test reuses a version consumed by a prior successful assign, and the reviewer OCC test reuses the creation-time version consumed by the v1 certification grant.
8. Earlier session fixes retained: removed the nonexistent `PolicyCategory.child_category_count`, `appeal_credits` -> `appeal_credits_remaining`, decide-description certification contradiction, transparency-report null-vs-zero defaults, the wellness/SUSPENDED cascade's queue-counter and `sla_due_at` ambiguity (explicitly NOT recomputed), and activation no longer moving `Reviewer.status`.

### Orchestrator post-step action (not part of subagent summary)

The scaffold generator copied the difficulty directive line `Generate task harder than expert level!` verbatim into `SCAFFOLD.yaml`'s `scenario:` block, from which it would have reached PRD.md via the doc generator. Per the pipeline contract (the directive is for the scaffold generator ONLY and must never leak into PRD.md), the orchestrator deleted that line plus its trailing blank line from `SCAFFOLD.yaml` (lines 2–3), leaving the scenario text itself byte-verbatim. Verified afterwards: 0 occurrences of "harder than expert" remain in SCAFFOLD.yaml, the file still parses as YAML with 14 top-level keys, and neither `scaffold_difficulty_design` nor `scaffold_corner_design` is present. The two design files each parse with exactly their single expected top-level key.

## Step 3: Copy shared files — 2026-09-04T19:16:17.685Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` → `workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T19:33:00.000Z

Subagent summary (verbatim):

PRD generation for task_2759 is complete and all three Hard Contracts verify PASS.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/workspace/PRD.md`

- `wc -lc` → **422 lines, 93172 bytes**
- `tail -30` → ends on the complete final table row `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |`, i.e. the last row of the §5 error catalogue — a real section boundary, not mid-sentence or mid-table.
- Structure: §1 Introduction, §2 Global Specifications (2.1 RBAC → 2.10 Conserved Quantities, with §2.2 copied byte-identically from the skill's `section-2.2-response-structure.md`), §3 Business Logic in 9 subsections, §4 Endpoint Definitions (48-row 4-column table), §5 Error Code Catalogue (61-row 2-column table).
- Grep for meta-commentary (`harder than`, `expert level`, `difficulty`, `corner case`, `test recipe`) and for fuzzy words (`approximately`, `roughly`, `conservatively`, `as appropriate`, `etc.`) returns zero hits.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml` and every sibling task directory were never opened, grepped or referenced.

## Field coverage check
```
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body: 73 required, 73 present, 0 missing
- endpoints[].query_params: 49 required, 49 present, 0 missing
Status: PASS
```
(Also 1/1 path params, 61/61 error ids, 6/6 roles, 36/36 global-constant leaf values, 31/31 state values, all enum values. Verified over two independent passes with different matchers — word-split token set, then exact `\b`-anchored backticked-span search.)

## Rule coverage check
```
- validations[] with priority: 48 checked, 48 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 41 checked (9 machines, 48 from->to edges once compound labels expand), 41 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 48 checked, 48 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 131 side_effects across 28 endpoints checked, 131 expressed; 48/48 endpoint role lists match the scaffold exactly, 0 missing
- entities[].fields[] structured content: 133 checked, 133 reconstructible from prose, 0 missing
- sibling-branch symmetry: 27 groups checked, 27 with equal prose density, 0 asymmetric
Status: PASS
```

## Path purity check (§3 only)
```
- backtick tokens scanned: 1008
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## Notes

- The one-and-only repair this pass: `REPEAT_BONUS_PER_POINT` was written as the words "one hundredth of a point"; changed to the literal `0.01` so every global-constant value now appears verbatim (§3.3, `effective_confidence`).
- The large "missing identifier" lists from the earlier verification run were confirmed to be a checker tokenizer bug, not PRD gaps: the fenced ```json blocks in the verbatim §2.2 section made unpaired backticks mis-slice the document. Stripping fenced blocks before extracting inline backticks resolved it, and both subsequent passes came back with empty diffs.
- Residual "absent" tokens reported by the rule-coverage sweep were verified to be scaffold-internal labels with no implementer-facing surface — calculation names (`routing_disposition`, `queue_selection`, `review_sla_due_at`, `transparency_enforcement_volumes`), pattern tags (`weighted_scoring`, `waterfall_allocation`, `constraint_propagation`, `input_set`), and YAML-dump newline artifacts. The corresponding real entity fields (`disposition`, `sla_due_at`, etc.) are all present in prose. `CONGESTION_MULTIPLIER` is expressed by its three numeric branches (1.0 / 1.5 / 2.0 at depths ≤5, 6–15, ≥16) rather than by invented tier names, matching the scaffold's range-keyed form.
- One scaffold inconsistency was resolved in favour of the state machine plus `routing_disposition` calculation (authoritative) over a looser endpoint description: T1/non-`STANDARD` human-review cases open in `PENDING_ASSIGNMENT` at `escalation_tier` 1 with a 30-minute deadline; only `LEGAL_REQUEST` cases are born `ESCALATED` at tier 2 with 1440 minutes and increment `open_case_count` only. This is stated explicitly in §3.3 so the implementer cannot read it either way.

### Orchestrator verification (not part of subagent summary)

Independently re-checked the known doc-generator truncation failure mode: `wc -lc` = 422 lines / 93172 bytes; `tail -12` ends on the complete table row `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |`; six top-level headings present in order (§1 Introduction, §2 Global Specifications, §3 Business Logic, §4 Endpoint Definitions, §5 Error Code Catalogue). Not truncated — no regeneration needed. `grep -ci "harder than expert\|expert level"` = 0, confirming the Step 2 leak strip held all the way through to the PRD.

## Step 6: Generate implementation — 2026-09-04T19:59:00.000Z

(Steps 5 and 6 were launched concurrently. Step 6 returned first; the Step 5 entry follows below.)

Subagent summary (verbatim):

Implementation complete.

## Modules (all under `/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/workspace/implementation/`)

| file | lines | role |
|---|---|---|
| `core.py` | 608 | 61-entry error→HTTP catalogue, `ApiError`/`fail`, all global constants, ISO-8601 parse/format (3 fractional digits), logical `Clock`, in-memory `Store`/`db`, `Decimal` 4-dp + ceiling helpers, response envelope, auth/authorization, pagination, body well-formedness validators |
| `ser.py` | 143 | one serializer per entity; `detection_signal` deliberately omits `updated_at`/`version` |
| `svc.py` | 325 | lookups, full account-ledger recompute, strike-point formula, queue selector, SLA congestion arithmetic, dual accuracy variants + accuracy gate, wellness/suspend release, 7-predicate reviewer eligibility, ranked reviewer selector, directed-target vetting ladder |
| `case_ops.py` | 178 | case minting (classifier / legal / manual / auto-action) and the decision cascade |
| `r_accounts.py` | 116 | accounts, content items, per-content signal list |
| `r_policy.py` | 307 | categories, versions, back-test, revise, activate (4 ordered cascades) |
| `r_workforce.py` | 219 | queues, reviewers, certifications, wellness break, return-to-duty |
| `r_detection.py` | 114 | effective confidence, 5-branch routing disposition, signal ingest |
| `r_cases.py` | 289 | create/assign/decide/escalate/return-to-queue/get/list |
| `r_appeals.py` | 205 | file, route to independent reviewer, resolve (UPHELD + 6-cascade OVERTURNED) |
| `r_qa.py` | 135 | audit-sample draw, audit, dispute |
| `r_reports.py` | 195 | transparency reports (open/compute/publish/get) + `_clock/set_current_utc` |
| `app.py` | 76 | app factory, 8 blueprints at `url_prefix="/moderation"`, `ApiError`/404/405/HTTPException/Exception handlers all emitting the error envelope |
| `start.sh` | 10 | guarded pip install, `exec python3 app.py`, honours `$PORT` |
| `requirements.txt` | 1 | `Flask>=3.0.0` |
| **total** | **2921** | |

## Endpoints: 48 / 48

`app.url_map` yields exactly 48 non-static rules, and a method+path diff against the 48 `method:`/`path:` pairs in `SCAFFOLD.yaml` is an exact 1:1 match (no extras, no omissions). Note `/moderation/accounts` is POST-only per the scaffold — there is no account collection list, so a `GET` there correctly returns 405.

## OCC modelling

Every mutable entity carries `version` (starts at 1, `+1` on any mutation including server-initiated cascades) via `core.base_fields` / `core.touch`; `DetectionSignal` is the exception and carries only `id` + `created_at`. Two endpoints take a caller-supplied expectation, both **required** integer inputs and both evaluated **last**, after every other rejection tier (PRD §2.8 tier 11):

- `POST /moderation-cases/{id}/assign` — `expected_case_version` vs the case's `version` → `ERR_STALE_CASE_VERSION` (412). Checked after path/body id resolution, `ERR_CASE_ALREADY_DECIDED`, the whole directed-target vetting ladder and `ERR_NO_ELIGIBLE_REVIEWER`; only then do the counter/exposure moves happen.
- `POST /reviewers/{id}/certifications` — `expected_reviewer_version` vs the reviewer's `version` → `ERR_STALE_REVIEWER_VERSION` (412). Checked after `ERR_REVIEWER_NOT_FOUND`, `ERR_POLICY_VERSION_NOT_FOUND` and `ERR_POLICY_VERSION_NOT_CERTIFIABLE`.

A single request produces exactly one `version` bump per record, not one per derived-field recompute.

## Smoke test — passed

Booted with `PORT=18759 bash start.sh`, exercised ~25 requests, then a second cold boot on `PORT=18760`. Verified: 401 on missing headers; `ERR_DUPLICATE_HANDLE` 409; category/version creation; back-test → `BACKTESTING` with `backtest_divergence_rate` 0.0; `ERR_SEGREGATION_OF_DUTIES` when the author tries to activate, then success under a second PolicyManager; certification with OCC, and 412 `ERR_STALE_REVIEWER_VERSION` on replay; `ERR_NO_ACTIVE_POLICY_VERSION` before activation; signal → `HUMAN_REVIEW` with a pinned case whose `sla_due_at` = now + ceil(120 × 1.0 / 2) = 60 min; assign charging `exposure_points_charged` 9 (weight 3 × VIDEO 3); decide REMOVE → `strike_points_applied` 4, content `REMOVED`/`ACTIONED`, account `strike_points` 4 / `standing` `LIMITED`; appeal filed (credit 3→2); auto-routed to an independent SENIOR reviewer; OVERTURNED → content `REINSTATED`/`CLEAR` with `reinstated_at`, account fully unwound to 0/0/`GOOD_STANDING` with the credit refunded to 3, decider's `appealed_count` 1 and `accuracy_score_blended` recomputed (gate correctly did not fire at sample size 1 < `MIN_GATE_SAMPLE`); clock forward OK and `ERR_CLOCK_NOT_MONOTONIC` 422 backwards; report open, `ERR_REPORT_PERIOD_OVERLAP` 409, compute → `COMPUTED`; unknown route → envelope 404. Cold boot on 18760 returned `total_count: 0` and clock `2026-08-01T00:00:00.000Z`, confirming an empty unseeded store on every launch.

Both servers were killed by resolving the PID from `ss -ltnp` on their own port (3049459, 3105133); no `pkill` was used, and both ports confirmed free. `__pycache__` removed. A grep for `sqlite`, `open(`, `json.dump`, `pickle` and `/tmp` across all modules returns nothing — storage is purely in-process dicts.

### Orchestrator note on Step 5/6 concurrency

Both agents were launched to run concurrently, but due to an orchestrator slip the two Agent calls went out in two successive assistant messages rather than one, so Step 6 started roughly 30 seconds after Step 5 rather than simultaneously. The physical-isolation guarantee (impl generator cannot see `test_suite/` because it does not exist yet) was therefore replaced by an explicit hard prohibition in the Step 6 prompt forbidding any read/list/glob/grep of `test_helpers/` or `test_suite/` and of both SCAFFOLD design indices. Timeline evidence supports that the prohibition held: at the 9-minute mark the implementation already had 6 modules while `test_helpers/`/`test_suite/` did not yet exist on disk at all, and `test_suite/` was still empty when Step 6 exited. Step 6's summary traces every behaviour to PRD/SCAFFOLD sections and cites no test artifact.

## Step 5: Generate unit tests — 2026-09-04T21:10:00.000Z

Subagent summary (verbatim):

Test infrastructure and suite for `task_2759_content_moderation_operations` are complete and statically verified.

## Output location (as mandated)
Both at the TASK ROOT — nothing under `workspace/` (verified by `find workspace -name "test_*"` → empty):
- `/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/test_helpers/`
- `/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/test_suite/`

## Totals
- **16 test files + conftest.py; 120 test functions; 3,923 lines in `test_suite/`.**
- `test_helpers/`: 9 modules, 3,023 lines (`__init__` 108, `api_client` 519, `api_errors` 157, `assertions` 306, `constants` 185, `factories` 343, `fixtures` 1001, `test_users` 121, `types` 283).

Per-file test counts (lines in parens): `test_01_account_registration_and_content_intake` 6 (207), `test_02_api_conventions_clock_and_lookups` 7 (223), `test_03_policy_taxonomy_authoring` 8 (351), `test_04_policy_version_lifecycle_and_backtesting` 7 (320), `test_05_detection_signal_scoring_and_routing` 8 (338), `test_06_case_deadlines_and_legal_origin` 5 (243), `test_07_reviewer_onboarding_certification_and_wellness` 10 (424), `test_08_case_assignment_eligibility` 7 (354), `test_09_assignment_selection_and_occ` 8 (360), `test_10_case_decision_and_strike_ledger` 7 (385), `test_11_case_escalation_and_return_to_queue` 7 (329), `test_12_policy_pinning_and_recertification` 6 (302), `test_13_appeals_intake_and_resolution` 9 (401), `test_14_appeal_overturn_compensation` 6 (395), `test_15_quality_audit_and_accuracy_gate` 9 (490), `test_16_transparency_reporting` 10 (495).

## Design-index audit (machine-checked against both yamls)
- 96 non-stub instances exist (23 Difficulty + 73 Corner); **all 96 are covered, 0 dangling tags, 0 stub tags, exactly one `Design:` line per test and always the final docstring line.**
- Every Difficulty instance has ≥2 tests (requirement met for all 9 rule_ids).
- **Zero instances skipped** — every non-stub instance passed the PRD-first two-condition filter. The 21 `excluded_because:` stubs were not translated, as specified.
- One Corner instance (`state_machines/return_to_queue_from_assigned_rejected_as_invalid_transition`) legitimately carries two tests (ASSIGNED-origin and PENDING-origin refusals); every test still maps to exactly one instance.

## PRD-citation audit
120 quotes (one per test) normalised and matched against `workspace/PRD.md`: **120/120 verbatim.** Two were repaired during the audit — a quote in `test_13` was missing the PRD's `**` bold markers, and a thin 6-word citation in `test_11` was extended to the full two-sentence rule about exposure not being refunded.

## Static checks (no server started, no `pkill` run)
- `python3 -m py_compile test_helpers/*.py test_suite/*.py` → clean.
- `python3 -m pytest test_suite --collect-only -q` → **120 tests collected in 0.73s, 0 errors.**
- `pyflakes` clean apart from intentional re-export/fixture-registration imports in `test_helpers/__init__.py` and `test_suite/conftest.py`; three genuinely unused imports were removed (`typing.List` in `api_client`, `math` in `assertions`, `create_policy_version_payload` in `test_04`).
- No `skip`/`xfail`/`TODO`/placeholder bodies; no occurrence of "scaffold" or design-file names anywhere in generated code; all 120 tests anchor the logical clock (directly via `clock_at_t0`/baseline fixtures or through module helpers that call `build_*_baseline`).
- `__pycache__`/`.pytest_cache` removed afterwards.

## Design-vs-PRD deviations to record (PRD won in each case)
1. **Legal-case queue counter** (`test_06`): the design instance asserts `unassigned_case_count == 1`; PRD line 229 says an `ESCALATED` case is not queue-assignable so it does not rise. Asserted **0**.
2. **`ERR_POLICY_VERSION_NOT_CERTIFIABLE` status**: design says 422; PRD §3.4/§5 and the registered error map say **409**. Used 409.
3. **Certification success status** is ambiguous between 200 and 201 in the PRD; asserted through `world.certify`/`get_success_data`, which accept any 2xx, leaving the code unpinned.
4. **Off-shift re-entry instance** required moving the clock backwards (22:00Z → 19:59Z), which violates the PRD's monotonic clock; proven instead with a night-shift reviewer (`shift_start_local_hour=20, shift_end_local_hour=24`) accepted at 22:00Z.
5. **`exposure_points_charged` on an unassigned case** is not PRD-specified; that single sub-assertion from the design instance was dropped.

### Orchestrator verification (not part of subagent summary)

Confirmed independently that no test artifacts leaked into the implementer sandbox: `find workspace -name "test_*" -o -name test_helpers -o -name test_suite` returns nothing. `test_suite/` holds 17 entries (16 test modules + conftest.py) and `test_helpers/` 9 modules, both at the task root. No `__pycache__`/`.pytest_cache` residue anywhere under the task directory.

## Step 7: Run tests and iterate — 2026-09-04T21:41:00.000Z

Subagent summary (verbatim):

Clean sweep confirmed. Two iterations total.

## Summary

**Iterations run:** 2

**Final sweep (8 parallel rounds, all present on disk):**
| round | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| passed/total | 120/120 | 120/120 | 120/120 | 120/120 | 120/120 | 120/120 | 120/120 | 120/120 |

Iteration 1 was 117/120 in **all eight** rounds with the identical three failures — fully deterministic, no flakiness anywhere in the suite.

**Tests deleted:** none. (No failing test was found to lack PRD coverage as a whole; one individual assertion was dropped, below.)

**Fixes applied to `test_suite/`:**
- `test_11_case_escalation_and_return_to_queue.py::test_escalate_branch_refunds_exposure_and_rewrites_the_deadline` — removed the single assertion `strike_points_applied is None` on a non-decided case (**DEFAULT-VALUE / COMPUTED-FIELD SILENCE**, STEP 1c partial-coverage split). PRD names `strike_points_applied` only as a value "computed once at decision time" (§3.5) and as the ledger summand (§2.10); it never states the field's pre-decision value, and §2.6 declares strike points integers, so a faithful reader may equally initialise it to `0` or to `null`. All other assertions in the test (escalation posture, exposure refund, 30-minute deadline, sibling case untouched) were kept intact.
- `test_10_case_decision_and_strike_ledger.py::test_decide_on_pending_assignment_case_rejected_as_not_assigned` — the test read §3.5's *enumeration* of decide guards as an evaluation order, asserting `ERR_CASE_NOT_ASSIGNED` while acting as a `Reviewer` on a case whose `assigned_reviewer_id` is null. §2.8 is the PRD's explicit precedence contract and puts Ownership (tier 6, `ERR_NOT_CASE_OWNER`) strictly before Lifecycle state (tier 9), so the implementation was right. Rather than weaken the exact-error assertion, the test was made **more** faithful: it now reaches the tier-9 state guard through the `LegalCounsel` arm — §2.8 tier 6 is scoped to "A reviewer acting on a case" and §2.1 says a `LegalCounsel` `X-User-ID` "never resolves to an entity row" — on a `LEGAL_REQUEST` case returned to its queue, which §3.5 says retains `escalation_reason` so the tier-2 legal restriction passes while the status is `PENDING_ASSIGNMENT`. The `ERR_CASE_NOT_ASSIGNED` assertion is preserved verbatim.

**Fixes applied to `test_helpers/`:** none — no fixture, factory or header builder was found inconsistent with PRD.

**Fixes applied to `implementation/`:**
- `r_policy.py`, `create_category()` — moved the `ERR_CHILD_SEVERITY_EXCEEDS_PARENT` check ahead of the `ERR_DUPLICATE_CATEGORY_CODE` scan. §2.8 tier 10 fixes the inner order as "…`ERR_CHILD_SEVERITY_EXCEEDS_PARENT`; `ERR_QUEUE_SPECIALTY_MISMATCH`; **then** the uniqueness and clock rules `ERR_DUPLICATE_CATEGORY_CODE`…", so a payload breaking both rules must report severity (422), not the code collision (409).

No implementation check was removed or weakened, no skip/xfail was added, no endpoint or field was invented, and storage remains in-memory-only. `worklog.md` was not read or modified. The temporary smoke server used to spot-check the three fixes (port 17593) was resolved by port via `ss -ltnp` and stopped; the port is free.

### Orchestrator verification (not part of subagent summary)

Independently re-read all eight `workspace/implementation/results.$i.json` files after the agent exited: every round reports `passed == total == 120` with `failed == 0`, timestamped 21:31Z (the final sweep), so the clean-sweep claim is backed by artifacts on disk rather than by the agent's assertion alone. The orchestrator also observed the iteration-1 sweep directly at 21:18Z showing an identical 117/120 in all eight rounds, independently confirming the failures were deterministic rather than load-induced. Step 8 is therefore NOT skipped: Step 7 applied 1 `implementation/` fix and 2 `test_suite/` fixes.

## Step 8: Finalize PRD — 2026-09-04T21:44:00.000Z

Not skipped: Step 7 applied 1 `implementation/` fix and 2 `test_suite/` fixes across 2 iterations.

Subagent summary (verbatim):

`PRD_FINALIZED.md` is written and verified: 422 lines in both files (identical line count, 0.0% line delta; +678 bytes, +0.73% by size), last line still `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |`, and `diff` shows exactly two changed regions.

## Step 7 items → PRD disposition

| Step 7 item | Disposition |
|---|---|
| test_suite: dropped `strike_points_applied is None` on a non-decided case | **PRD silence → edited §3.5** |
| test_suite: `test_decide_on_pending_assignment_case_rejected_as_not_assigned` rewritten to reach tier 9 via the `LegalCounsel` arm | **PRD internally ambiguous / self-contradictory → edited §3.5** |
| implementation `r_policy.py::create_category` — severity check moved ahead of duplicate-code scan | **No edit.** §2.8 tier 10 already fixes the inner order verbatim (`…ERR_CHILD_SEVERITY_EXCEEDS_PARENT; ERR_QUEUE_SPECIALTY_MISMATCH; then the uniqueness and clock rules ERR_DUPLICATE_CATEGORY_CODE…`). This was a pure impl-vs-PRD mismatch that Step 7 fixed in the impl; PRD prose kept byte-identical. |

## Changes

- **§3.5 (decide guard list)** — *revise* — the four-condition enumeration is now explicitly flagged as *not* an evaluation order, with §2.8's tier 6 ownership check stated to precede every tier 9 lifecycle-state check; the status guard is split per arm (`ASSIGNED` for a `Reviewer`, `ESCALATED` for `LegalCounsel`, any other status → `ERR_CASE_NOT_ASSIGNED`); the `ERR_NOT_CASE_OWNER` guard is scoped to a `Reviewer` actor and noted as absent on the legal arm — `implementation/r_cases.py:172-193`.
- **§3.5 (`strike_points_applied` paragraph)** — *insert* — pre-decision value is the integer `0`, not null, and the frozen value survives an overturn (exclusion runs through `is_overturned`) — `implementation/case_ops.py:31`, `implementation/svc.py:80-84`.

## Per-edit pre-edit search log

**Edit 1 — decide guard list.**
(a) Subject: which guard is reported first on `POST /moderation-cases/{id}/decide`, the scope of `ERR_NOT_CASE_OWNER`, and the per-arm status precondition.
(b) Paths enumerated and read: `r_cases.py::decide_case` (full body — auth → `LegalCounsel` `escalation_reason` peek → body validation → `find` → ownership (Reviewer-only, line 172) → `ERR_CASE_ALREADY_DECIDED` (175) → per-arm status/active/certification (178-193)); `r_cases.py::escalate_case` (ownership at 206 before `ERR_CASE_ALREADY_DECIDED` 208 and `ERR_INVALID_CASE_TRANSITION` 210 — unscoped by role, since both `Reviewer` and `QAAuditor` must be the holder); `r_cases.py::assign_case` (no ownership tier; stale-version last at 119-122); `r_qa.py::dispute_sample` (ownership at 91 before `ERR_AUDIT_NOT_DISPUTABLE` at 94); `r_qa.py::draw_sample` (`ERR_SEGREGATION_OF_DUTIES` at 31 before `ERR_CASE_NOT_DECIDED` at 33); `r_appeals.py` grep for `ERR_NOT_APPEAL_REVIEWER` / `ERR_APPEAL_NOT_UNDER_REVIEW` (124 before 127). `case_ops.py::record_decision` read to confirm `assigned_reviewer_id` is *not* cleared at decision, so a repeat decide by the owner still reaches `ERR_CASE_ALREADY_DECIDED`.
(c) Wording adjustments made: the "ownership before lifecycle" claim is attributed to §2.8 rather than asserted as a new universal, so it stays true of escalate/dispute/appeal-resolve too; the ownership clause is scoped with "when the actor is a `Reviewer`" rather than being dropped, because escalate still applies it to a `QAAuditor` actor; the original "`ESCALATED` with `escalation_reason` `LEGAL_REQUEST` (`ERR_CASE_NOT_ASSIGNED`)" was re-cut to attach only the *status* half to `ERR_CASE_NOT_ASSIGNED`, since the impl reports the `escalation_reason` half as tier-2 `ERR_UNAUTHORIZED` (already stated by the unchanged legal-arm paragraph two paragraphs later).

**Edit 2 — `strike_points_applied` default and post-overturn value.**
(a) Subject: the value of `strike_points_applied` on any case that is not (or is no longer validly) a decided, counted case.
(b) Paths enumerated: `grep -rn strike_points_applied implementation/` → all five sites read: `case_ops.py:31` (`_blank_case`, literal `0`, shared by all three constructors — `create_queued_case` PENDING_ASSIGNMENT, `create_legal_case` ESCALATED, `create_auto_action_case` DECIDED), `case_ops.py:123` (auto-action overwrite), `case_ops.py:152` (`record_decision`, both HUMAN and LEGAL arms), `svc.py:84` (`recompute_account`, skips non-`DECIDED` and `is_overturned` cases), `ser.py:100` (emitted raw, so `0` reaches the wire). Also confirmed by grep that `r_appeals.py` never writes the field on the overturn cascade, and no reset exists on escalate/return-to-queue/wellness/suspension paths.
(c) Wording adjustment: added the "keeps its frozen value even after an overturn" half-sentence after finding the overturn cascade leaves the field alone — without it, "frozen thereafter" plus §3.7's "permanently excludes that case from the strike ledger" could be read as zeroing the field. Said "the integer 0" (not "0 or its computed value") to stay consistent with §2.6's integer declaration and with the `NO_ACTION` case, which legitimately stores `0` while `DECIDED`.

### Orchestrator verification (not part of subagent summary)

`cmp` confirms `PRD_FINALIZED.md` is NOT byte-identical to `PRD.md` (422 lines / 93850 bytes vs 422 lines / 93172 bytes; `diff` reports 4 changed lines across 2 regions). Tail still ends on the complete final error-catalogue row, so the file is not truncated.

## Step 9: Complete PRD — 2026-09-04T22:15:00.000Z

Always runs (no skip condition). Executed as **three sequential module-partitioned passes** over one shared `PRD_COMPLETED.md`, rather than one monolithic scan, so that no single subagent had to hold 2,921 lines of implementation plus a 94KB PRD in one context (a monolithic Step 9 tends to under-scan and leave the output byte-identical to its input). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 were explicitly forbidden from copying, and each pass spot-checked that the previous passes' edits survived. Partition:

- **Pass 1** — `core.py`, `app.py`, `ser.py`, `svc.py`, `case_ops.py` (conventions, envelope, pagination, clock/ISO grammar, decimals, serializers, calculations, case minting + decision cascade). **18 changes: 16 ambiguity-pins, 2 mismatch-revisions.**
- **Pass 2** — `r_accounts.py`, `r_policy.py`, `r_workforce.py`, `r_detection.py` (intake, taxonomy, version lifecycle + activation cascades, workforce, wellness, detection routing). **19 changes: 18 ambiguity-pins, 1 mismatch-revision.**
- **Pass 3** — `r_cases.py`, `r_appeals.py`, `r_qa.py`, `r_reports.py` (case lifecycle, appeals + overturn compensation, QA audit, transparency reporting). **22 changes: 18 ambiguity-pins, 4 mismatch-revisions.**

**Total: 59 changes — 52 ambiguity-pins, 7 mismatch-revisions.** `PRD_FINALIZED.md` 422 lines / 93,850 chars → `PRD_COMPLETED.md` 423 lines / 109,337 chars (+15,487 chars, +16.5%). The single added line is one new bullet inside §2.2's existing error-format bullet list; every other edit is an in-paragraph insert or revision. No new sections.

### Pass 1 summary (verbatim)

Pass 1 complete. Structure is intact — headings byte-identical, table row counts identical, file ends on the correct final catalogue row.

**Setup:** `cp PRD_FINALIZED.md → PRD_COMPLETED.md` done; only PRD_COMPLETED.md edited. Audited exactly my five modules: `core.py`, `app.py`, `ser.py`, `svc.py`, `case_ops.py`. Did not audit any `r_*.py` (read only two greps of them as cross-reference to learn what arguments `svc`/`case_ops` receive).

**Line/char counts:** PRD_FINALIZED.md `422 93850` → PRD_COMPLETED.md `423 99527` (+1 line, +5677 chars). The single extra line is one new bullet inside the existing §2.2 error-format bullet list; no new sections or paragraphs.

**Counts:** 18 changes total — 16 ambiguity-pins, 2 mismatch-revisions.

**Changes:**
- §2.1 — revise — ambiguity — an empty header value counts as absent; role names are case-exact (`core.py:391-395`)
- §2.2 success bullets — revise — ambiguity — `api_request_id` is `req_` + exactly 20 uppercase-alphanumeric characters (`core.py:338-342`)
- §2.2 error bullets — insert — ambiguity — `message` is advisory, contract is `error_id`+status; unrouted path → 404, bad method → 405, server fault → 500, all with `ERR_INVALID_REQUEST` despite §5 listing it at 400; trailing slash tolerated (`app.py:37,47-66`)
- §2.3 — revise — ambiguity — non-integer `limit`/`offset` text is `ERR_INVALID_REQUEST` (`core.py:417,424`)
- §2.3 — insert — ambiguity — `created_at` ties broken by server insertion order, never by `id` (`core.py:322,432-433`)
- §2.3 — insert — ambiguity — `has_more` formula; unrecognised enum filter → `ERR_INVALID_REQUEST`; id/text filters exact-match to an empty page; undefined query params ignored (`core.py:363,443-456`)
- §2.4 — insert — ambiguity — tolerant ISO 8601 input grammar (`T`/space, optional seconds, optional fraction, optional `Z`/`±HH:MM`/`±HHMM`), missing offset read as UTC, offsets normalised, sub-millisecond truncated on render (`core.py:180-222`)
- §2.5 — revise — ambiguity — a recomputation advances `updated_at`/`version` even when the value is unchanged (`core.py:326-331`)
- §2.6 — insert — ambiguity — four-decimal figures emitted as JSON numbers, so trailing zeros are suppressed (`0.5000`→`0.5`) (`core.py:259-263`, `ser.py:47-49`)
- §2.8 tier 3 — insert — ambiguity — explicit JSON `null` == omitted; non-object/unparseable body → `ERR_INVALID_REQUEST`; absent/empty body == empty object; booleans rejected as numbers (`core.py:463-482,508,527`)
- §2.10 — insert — **mismatch** — `lifetime_removed_count` is a full recount of `DECIDED`/non-overturned `REMOVE` cases, not the delta the rest of the PRD implies (`svc.py:76-90`)
- §3.3 — insert — ambiguity — detection signal stores the submitted `policy_category_code` and exposes no resolved category id (`ser.py:81-91`)
- §3.3 — revise — ambiguity — an `AUTO_ACTION` case's `sla_due_at` stays null (`case_ops.py:112-120`)
- §3.3 — insert — ambiguity — full floor list for a freshly minted case (booleans false, three integers 0 not null, six references null) (`case_ops.py:13-40`)
- §3.4 — revise — ambiguity — language/specialty predicates apply only when a queue is in play (`svc.py:277-281`)
- §3.4 — insert — ambiguity — the directed-target ladder omits the `exclude_reviewer_ids` and self-assignment predicates (`svc.py:305-325`)
- §3.5 — revise — ambiguity — `rationale` (and the `reason` on return-to-queue / wellness break) is validated but never persisted (`case_ops.py:13-40`, `r_cases.py:168` confirms discard)
- §3.5 — insert — ambiguity — a decided case retains `assigned_reviewer_id` and `queue_id` (`case_ops.py:137-178`)
- §3.7 — revise — **mismatch** — appeal routing checks the *conditional* certification target of §3.4, not unconditionally the pinned version; no queue and zero charge (`svc.py:236-242`)
- §3.8 — insert — ambiguity — the accuracy gate acts only on an `ACTIVE` reviewer, and a demotion shares the recomputation's single `version` increment (`svc.py:185,175`)

One finding worth flagging to whoever owns the later passes: every field emitted by `ser.py` is already named somewhere in the PRD, so there were no serializer field-list gaps — the serializer risk in this task was field *nullability/floor* wording, not missing fields.

### Pass 2 summary (verbatim)

Verification passed. Final report:

## Confirmation

- **No `cp` was run.** All 19 changes were surgical `Edit` calls against the existing `PRD_COMPLETED.md`. `PRD.md` and `PRD_FINALIZED.md` were never edited.
- **Pass 1's edits survive.** A full `difflib` diff against `PRD_FINALIZED.md` still shows all 21 of pass 1's changed lines (17, 46, 72–73, 79, 81, 83, 89, 98, 108, 128, 152, 192, 198, 200, 218, 222, 234, 236, 264, 284). Spot-checked and present: the `api_request_id` "exactly twenty characters" sentence (§2.2), the `lifetime_removed_count` "observable effect of that recount" sentence (§2.10), the trailing-slash/404-405-500 bullet (§2.2), the signal-listing ordering clause (§2.3), and the accuracy-gate shared-`version`-increment sentence (§3.8).
- **Structure intact.** All six top-level headings plus every `###` subsection present; file still ends on `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |`.

## Counts

| | lines | chars |
|---|---|---|
| before | 423 | 99,527 |
| after | 423 | 104,159 |

Line count is unchanged because every edit was an in-paragraph insert or revision — no new paragraphs or sections.

**18 ambiguity-pins, 1 mismatch-revision.**

## Changes

- §3.1 — revise — ambiguity — `external_handle` uniqueness is exact, case-sensitive, whole-string (no trim/case-fold); a 2-char non-uppercase `region_code` is malformed input — `r_accounts.py:23,28`
- §3.1 — insert — ambiguity — `BANNED` is the only gating posture; `LIMITED`/`SUSPENDED` still permit ingestion — `r_accounts.py:63`
- §3.1 — insert — ambiguity — per-content signal listing carries every `disposition` incl. `DISCARDED`, defines no filter beyond `limit`/`offset`, and 404s on an unknown content id — `r_accounts.py:109-116`
- §3.2 — insert — ambiguity — a fresh draft also has null `activated_by_user_id`/`activated_at`; `version_label` is never checked for collision and a category may hold many concurrent `DRAFT`s — `r_policy.py:122-126`
- §3.2 — insert — ambiguity — back-test reads the author's `tier` as it stands **at replay time**, not historically — `r_policy.py:160`
- §3.2 — insert — ambiguity — back-test and activate read no request body at all; a body (even malformed JSON) is ignored — `r_policy.py:133,220`
- §3.2 — insert — ambiguity — revise: omitted fields keep stored values, `version_label`/`enforcement_action` are non-revisable and ignored, empty body accepted, and the threshold order check runs on the **merged** pair — `r_policy.py:183-201`
- §3.2 — insert — **mismatch** — the three activation guards are enumerated, not ordered: SoD (tier 8) precedes the lifecycle check (tier 9), so activating one's own never-back-tested draft yields `ERR_SEGREGATION_OF_DUTIES` — `r_policy.py:224-230`
- §3.2 — insert — ambiguity — cascade 2 appends to `pending_retraining_version_ids` with set semantics, both edits in one mutation (one `version` step), and unaffected reviewers are not touched — `r_policy.py:254-265`
- §3.2 — insert — ambiguity — cascade 3 leaves an already-flagged case untouched (no `updated_at`/`version` move); `ESCALATED`/`DECIDED` cases are never flagged — `r_policy.py:268-277`
- §3.3 — insert — ambiguity — a `DISCARDED` signal row is still persisted; queue selection runs only on the `HUMAN_REVIEW` branch, so `DISCARDED`/`AUTO_ACTION` succeed with no queue in existence — `r_detection.py:74-94`
- §3.3 — insert — ambiguity — a queue may be created against a `DRAFT` category, and queues carry no uniqueness constraint — `r_workforce.py:28-31`
- §3.4 — insert — ambiguity — equal `shift_start_local_hour`/`shift_end_local_hour` wraps to a 24-hour window (never off shift) — `r_workforce.py:77-78` + `svc.py:250-256`
- §3.4 — insert — ambiguity — `expected_reviewer_version` must be a non-negative integer; a negative/non-integer value fails at tier 3, not as staleness — `r_workforce.py:118`
- §3.4 — insert — ambiguity — a grant against an `ON_WELLNESS_BREAK` reviewer records the certification but leaves the status alone — `r_workforce.py:140-143`
- §3.6 — revise — ambiguity — `break_minutes` is any integer ≥ 1 with no upper bound — `r_workforce.py:153`
- §3.6 — insert — ambiguity — the overlap test only runs when both retained instants exist (a first break never collides), and each break overwrites the retained pair — `r_workforce.py:162-174`
- §3.6 — insert — ambiguity — the whole break is one mutation of the reviewer, so `version` rises by exactly one — `r_workforce.py:172-177`
- §3.6 — insert — ambiguity — return-to-duty reads no body (malformed JSON ignored) and moves nothing but `status` — `r_workforce.py:181-190`

**Not changed** (impl already uniquely pinned): every role list in my four modules matches §4's table exactly; the `effective_confidence` formula and the five-branch routing chain; all filter names/semantics on the six listings; the back-test sample predicate, ordering and empty-sample `0.0000`; the four activation cascades' order; queue counter floors; and all reviewer creation defaults.

### Pass 3 summary (verbatim)

Pass 3 complete. All 22 edits verified in place; no `cp` was ever run (Edit tool only).

## Verification
- **No `cp`**: confirmed — every change was a surgical `Edit` on `/home/ubuntu/github/CodingPRD/tasks/task_2759_content_moderation_operations/workspace/PRD_COMPLETED.md`.
- **Prior passes survive** (3 spot-checks, all present): §2.2 `api_request_id` shape ("starts with `req_`, followed by exactly twenty characters drawn from the uppercase letters and the decimal digits"); §2.10 `lifetime_removed_count` recount ("never an increment or a decrement"); §3.2 SoD-precedes-lifecycle ("tier 8 ahead of the lifecycle check of tier 9 … told `ERR_SEGREGATION_OF_DUTIES`").
- **Structure**: 6 top-level headings + all 19 `###` subsections intact (headings byte-identical to `PRD_FINALIZED.md`); §4 endpoint table = **48 rows**; §5 error table = **61 rows**; both tables byte-identical to `PRD_FINALIZED.md`; final line is `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |`.
- **Counts**: 423 lines / 104159 chars → **423 lines / 109337 chars**.
- **22 changes**: 18 ambiguity-pins, 4 mismatch-revisions.

## Changes
- §3.5 — insert — ambiguity — `origin: CLASSIFIER` on the hand-open path is an unrecognised enum member → `ERR_INVALID_REQUEST`, not an authz failure — r_cases.py:40
- §3.5 — insert — ambiguity — `legal_jurisdiction`/`legal_reference` on a `MANUAL_REPORT` are shape-checked at tier 3 then discarded, not rejected — r_cases.py:41-45,79
- §3.4 — insert — ambiguity — `expected_case_version` must be a non-negative integer (tier 3); assigning a `DECIDED` case is `ERR_CASE_ALREADY_DECIDED` — r_cases.py:88,99
- §3.4 — **revise** — **mismatch** — PRD claimed `exclude_reviewer_ids`/self-identity never disqualify a directed target; impl applies both *after* the seven-predicate ladder, yielding `ERR_NO_ELIGIBLE_REVIEWER` — r_cases.py:109
- §3.5 — insert — ambiguity — the legal decision arm looks up no reviewer row, so `ERR_REVIEWER_NOT_ACTIVE`/`ERR_REVIEWER_NOT_CERTIFIED` cannot arise from it — r_cases.py:189-193
- §3.5 — insert — ambiguity — the tier-2 `LegalCounsel`/`LEGAL_REQUEST` restriction only fires on a resolving `case_id`; otherwise the request falls through to tier 3 then `ERR_CASE_NOT_FOUND` — r_cases.py:160-164
- §3.5 — insert — ambiguity — escalation's ownership and `ACTIVE` guards bind the `QAAuditor` arm too — r_cases.py:206-215
- §3.5 — insert — ambiguity — escalation leaves the case's `exposure_points_charged` at its recorded figure (only the reviewer is refunded) — r_cases.py:222-223
- §3.5 — **revise** — **mismatch** — PRD said any non-`ESCALATED` return-to-queue is `ERR_INVALID_CASE_TRANSITION`; impl reports `ERR_CASE_ALREADY_DECIDED` for a `DECIDED` case — r_cases.py:238-242
- §3.7 — **revise** — **mismatch** — filing sets `review_status` to `APPEALED` unconditionally, including from the `CLEAR` a `NO_ACTION` decision left — r_appeals.py:61
- §3.7 — insert — ambiguity — the directed appeal-target ladder is shorter than §3.4's: `NOT_ACTIVE` → `NOT_CERTIFIED` → `NOT_ELIGIBLE_FOR_ESCALATION` only; shift/capacity/exposure unexamined, but they do constrain the server-selected pool — r_appeals.py:90-107
- §3.7 — insert — ambiguity — the resolving reviewer's own `status` is never examined — r_appeals.py:117-128
- §3.7 — insert — ambiguity — on overturn the credit refund + ledger recount + `standing` are one account mutation, so its `version` rises exactly once — r_appeals.py:159-160
- §3.7 — insert — ambiguity — an `AccountHolder` listing with somebody else's `account_id` gets `ERR_APPEAL_NOT_OWNED`, not an empty page; an omitted filter is silently scoped — r_appeals.py:187-191
- §3.8 — insert — ambiguity — a `QAAuditor` with no reviewer row cannot draw a sample (`ERR_UNAUTHORIZED`) — r_qa.py:21-23
- §3.8 — insert — ambiguity — no one-sample-per-case limit; a decided case may be drawn repeatedly — r_qa.py:36-50
- §3.8 — insert — ambiguity — any `QAAuditor` may audit (no `auditor_reviewer_id`/`role_class` check); `correct_outcome` with `AGREE` is accepted but forced null — r_qa.py:55,69
- §3.8 — insert — ambiguity — `DISPUTED → AUDITED` retains `dispute_note`/`disputed_at` — r_qa.py:68-73
- §3.8 — insert — ambiguity — `dispute_note` is required non-empty with no max; `verdict`/`correct_outcome`/`audited_at` retained; the accuracy gate runs on the dispute path — r_qa.py:86,97-104
- §3.9 — insert — ambiguity — `appeal_overturn_rate` is exactly `0.0000` when no category contributed a counted appeal — r_reports.py:133
- §3.9 — **revise** — **mismatch** — publication tests already-published *first*, so a `PUBLISHED` report yields `ERR_REPORT_ALREADY_PUBLISHED`, never `ERR_REPORT_NOT_COMPUTED` (§2.8 tier 9's inner order implied the opposite) — r_reports.py:161-164
- §3.9 — insert — ambiguity — publish reads no request body at all, so a malformed body is ignored rather than rejected — r_reports.py:154-157

### Orchestrator final verification (not part of any subagent summary)

- `cmp` confirms `PRD_COMPLETED.md` is NOT byte-identical to `PRD_FINALIZED.md` — the known Step 9 no-op failure mode did not occur. `diff` reports 97 changed lines.
- Line/char progression: `PRD.md` 422 / 93,172 → `PRD_FINALIZED.md` 422 / 93,850 → `PRD_COMPLETED.md` 423 / 109,337.
- Structure intact: 5 `##` section headings + 19 `###` subsections; §4 endpoint table 48 rows; §5 error table 61 rows; final line is the complete row `| \`ERR_STALE_REVIEWER_VERSION\` | 412 |` (not truncated).
- `grep -ci "harder than expert\|expert level"` = 0 in `PRD_COMPLETED.md` — the Step 2 difficulty-directive strip held through all three PRD generations.
- `implementation/` was untouched by Steps 8 and 9 (newest module mtime is `r_policy.py` at 21:26Z, i.e. the Step 7 fix, which predates the 21:31Z clean sweep), so the 8× 120/120 result files on disk remain valid for the shipped code. No re-sweep was needed.
- Housekeeping: removed `__pycache__` directories under `test_helpers/`, `test_suite/` and `workspace/implementation/`, plus the spliced `workspace/sweep.log`. No stray `worklog.md` anywhere but the task root; no `.bak` files.

**Pipeline complete.** All nine steps ran; `workspace/PRD_COMPLETED.md` is written.
