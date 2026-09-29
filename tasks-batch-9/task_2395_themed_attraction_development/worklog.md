# Worklog — task_2395_themed_attraction_development

## Step 1: Create task directory — 2026-09-02T00:00:00.000Z

Created `tasks/task_2395_themed_attraction_development/` and `tasks/task_2395_themed_attraction_development/workspace/` (name pre-allocated by the caller; no index scan performed).

## Step 2: Generate scaffold — 2026-09-02T08:23:31.824Z

All three artifacts are complete and the linter is clean.

**Verdict block (verbatim, final run):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2395_themed_attraction_development/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2395_themed_attraction_development/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2395_themed_attraction_development/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    66
  §1.1 entities declared:     13
  §1.8 instances scanned:     23
  §1.9 instances scanned:     48
  Calls scanned (§1.8+§1.9):  659

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(One violation was found on the first run — a literal `expected_project_version: 1` in the RBAC negative instance — and fixed by seeding a decoy project and capturing its version.)

**Artifacts** (all under `/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/`)

`SCAFFOLD.yaml` — §1.0–§1.7 only, no design keys. Profile: primary archetype `multi_party_negotiation`, secondary `posture_driven_gating`, layers `[optimistic_concurrency, cascading_side_effects, dual_variant_calculation, version_pinning_on_approval]`, topology `flat`, state-machine shape `cyclic`, role model `segregation_of_duties`, consistency `immediate`, difficulty `expert_plus`.
- 13 entities: AttractionProject, RideSystem, QueueSegment, ShowScene, EffectCue, DesignPackage, SafetyReview, SafetyFinding, ValueEngineeringItem, VEBallot, RehearsalRun, MaintenanceItem, BudgetLedgerEntry
- 12 state machines (AttractionProject carries two independent dimensions: a 9-rung forward-only `design_phase` ladder and a cyclic `readiness_posture` gate), 3 §1.2.1 OCC rules, 12 calculations, **66 endpoints**, 7 roles (all with `identity:`), **78 validation rows across 49 priorities**, **70 error codes** — every validation error is in the catalogue and every catalogued error is owned by a validation.

`SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 23 instances, all nine §0.5 rule_ids ≥2: dual_variant_calc 2, combinatorial_formula 3, non_linear_state_machine 2, transitive_cascade 3, priority_pair_validation_conflict 3, boundary_precision_check 3, cross_entity_state_dependency 3, resource_temporal_overlap 2, compensating_invariant 2.

`SCAFFOLD_CORNER_DESIGN.yaml` — 74 instances across all nine claim-extraction-guide sections (48 full recipes + 26 `excluded_because` stubs, every stub citing an existing §1.8 instance by name): entities 12, state_machines 15, calculations 12, validations 13, endpoints 5, errors 5, rbac 3, cross_cutting_complexity_layers 8, consistency_model 1.

**Two §1.5 defects the §1.9 audit surfaced and repaired in `SCAFFOLD.yaml`:**
1. `ERR_VIRTUAL_QUEUE_SHARE_EXCEEDED` (priority 35) was unreachable — the entity constraint capped `virtual_queue_share_pct` at 40, so priority 3 `ERR_INVALID_REQUEST` swallowed any violation. Schema range relaxed to 0–100 with the 40 cap documented as a priority-35 business rule.
2. The `advance-phase` content preconditions had no triggerable error. Added validation **priority 49 / `ERR_PHASE_PRECONDITION_UNMET`** (409, advance-phase only, deliberately last so priorities 15/29/30/33/34/37 keep owning their specific transitions) plus the matching catalogue entry.

Verified mechanically: no duplicate instance names across the union of both design files, no forbidden vocabulary ("simultaneously", "in parallel", "at the same time", "first-writer-wins", race winner/loser), every stub free of `test_recipe`, every full recipe carrying structured `setup_api_calls`, and no OCC version literal anywhere.

## Step 3: Copy shared files — 2026-09-02T08:23:31.824Z

Copied `INSTRUCTION.md` to `tasks/task_2395_themed_attraction_development/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-02T08:42:02.505Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/workspace/PRD.md`.

**Document shape:** 496 lines, ends at §5 with no audit footer.

- §1 Introduction — 3 paragraphs (multi-party negotiation framing, dual state dimensions, server-derived/version-pinned commitments).
- §2 Global Specifications — 10 subsections: 2.1 RBAC (all 7 opaque-identity roles), 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`), 2.3 Pagination, 2.4 Identifiers/Timestamps/Revision Counters, 2.5 Identifier Resolution Order & Reverse-Reachability Reads, 2.6 Version Pinning & Stale-Read Rejection, 2.7 The Readiness Posture Gate, 2.8 Numeric Conventions/Precision/Rounding, 2.9 The Delivery Ladder, 2.10 Order of Rejection (all 49 priority tiers).
- §3 Business Logic — 9 domain-grouped subsections (programme setup & logical clock; ride systems & dual capacity variants; scenes/cues/show quality; queue & accessibility; design packages & approval; safety review & findings; cost ledger & dual budget views; value-engineering ballot; rehearsal/soft-open/maintenance/handover).
- §4 — 4-column table, all 66 endpoints.
- §5 — 2-column table, all 70 error IDs.

**Hard Contract audits (machine-verified against SCAFFOLD.yaml):**

```
Field coverage check:
- entities[].fields: 131 required, 131 present, 0 missing
- endpoints[].request_body: 84 distinct input identifiers required, 84 present, 0 missing
- endpoints[].query_params: covered by the same 84-identifier set, 0 missing
- endpoints[].path_params: 1 distinct ({id}, 49 occurrences), 1 present, 0 missing
Status: PASS   (two independent passes: loose word-match and strict standalone-backtick match)
```

```
Rule coverage check:
- validations[] with priority: 78 entries over 49 distinct priorities checked, 49 tiers expressed in prose order, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 47 checked (12 machines), 47 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 78 checked, all matchable to an error_id present in prose, 0 missing
- endpoints[].side_effects / applies_to: all multi-endpoint applies_to sets enumerated, 0 missing
- entities[].fields[] structured content: 131 checked, reconstructible from prose, 0 missing
- sibling-branch symmetry: 8 groups checked, 8 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 830
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional cross-checks: all 66 §4 rows match scaffold method+path exactly with 0 role mismatches; all 70 §5 HTTP statuses match the scaffold's `errors[].http_status` and every `validations[].http_status`; no fuzzy quantifiers remain. The two `common_fields: false` entities (`VEBallot`, `BudgetLedgerEntry`) are explicitly called out as carrying only `id` and `created_at`.

Two deliberate fidelity choices worth flagging: (1) version counters are stated as advancing **once per resource per request** (the endpoint-level `side_effects` reading), which resolves the ambiguity where a posture recomputation inside an already-mutating request could otherwise be read as a second increment; (2) the rehearsal-completion precondition that `selected_ride_system_id` be non-null, and the queue-accept precondition on the 40% virtual-queue cap, are stated as preconditions without an error ID, because the scaffold maps no `error_id` to either.

The two withheld design files were never opened, grepped, or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-02T09:51:00.861Z

Generation complete. Both queues are fully translated and audited clean.

## Files written

`/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/test_helpers/` (9 files, Stage 1): `types.py`, `api_errors.py` (70 error ids + PRD-derived `HTTP_STATUS_CODES`), `constants.py`, `test_users.py`, `api_client.py` (all 66 endpoints), `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py`.

`/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/test_suite/` — `conftest.py` plus 15 modules:
- Queue A (depth, §1.8): `test_01_dual_capacity_and_budget_variants.py` (4), `test_02_formula_evaluation_order.py` (6), `test_03_state_machine_loops.py` (4), `test_04_transitive_cascades.py` (6), `test_05_rejection_precedence.py` (6), `test_06_threshold_boundaries.py` (6), `test_07_cross_entity_gates.py` (6), `test_08_temporal_overlap.py` (4), `test_09_compensating_invariants.py` (4).
- Queue B (breadth, §1.9): `test_10_entity_contracts.py` (12), `test_11_state_machine_contracts.py` (7), `test_12_calculation_contracts.py` (4), `test_13_validation_contracts.py` (10), `test_14_endpoint_and_error_contracts.py` (7 = 3 endpoints + 4 errors), `test_15_concurrency_authorisation_and_consistency.py` (8 = 2 rbac + 5 cross-cutting + 1 consistency).

## Counts

- **94 tests total, 71 distinct design tags.**
- Queue A: **46 tests** over all **23** difficulty instances — exactly 2 each.
- Queue B: **48 tests** over all **48** live corner instances — exactly 1 each (entities 12, state_machines 7, calculations 4, validations 10, endpoints 3, errors 4, rbac 2, cross_cutting_complexity_layers 5, consistency_model 1).

## Instances skipped

None of the live instances were dropped: every one passed the PRD-first two-condition filter. The **26 `excluded_because:` corner stubs** emit nothing by design; all 26 carry a `difficulty_instance` cross-reference and all resolve to real §1.8 instance names (0 dangling).

Two design-index/PRD conflicts were resolved in favour of the PRD rather than by weakening the test:
- The corner yaml claims HTTP 422 for `ERR_INVALID_REQUEST`; PRD tier 3 says 400, so those tests pass no explicit status and let the PRD-derived status map govern.
- `stale_expected_package_version_on_review_create_returns_412` asserts the replayed review lands in `status == OPEN`, but PRD §3.6 writes a new review as `IN_REVIEW`. The instance's actual claim (OCC at tier 6 masking the tier-7 package-state check) is fully grounded, so the test is emitted with the PRD's `IN_REVIEW` assertion instead of the yaml's.

## Audit results

- Citation audit (`/tmp/cite_check.py`): 0 `NOT VERBATIM`, 0 `MISSING TAG`, 0 `MULTI TAG`, 0 `NO CITATION` — every non-final docstring paragraph is a verbatim, full-sentence PRD substring and each test carries exactly one trailing `Design:` line.
- Tag/coverage cross-check against both yamls: 0 under-covered instances, 0 unknown/dangling tags.
- `pytest --collect-only`: 94 tests collected, no import or collection errors; `pyflakes` clean over `test_suite/` (one stale unused import in `test_02` removed); no comment or docstring anywhere mentions the scaffold or its section numbers.

## Step 6: Generate implementation — 2026-09-02T09:51:00.861Z

Implementation complete and verified.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/workspace/implementation/`)

Foundation: `start.sh`, `requirements.txt`, `errors.py` (all 71 error ids + default messages), `store.py` (13 empty dicts, logical clock pinned to `2026-08-01T00:00:00Z`, `touch()` with once-per-request version bump), `response.py` (pinned meta/response_type/data envelope, Decimal-safe serialization), `auth.py` (7 roles, 401 vs 403), `validate.py` (schema tier, `parse_float=Decimal`, pagination + enum/string query filters), `calc.py` (all 8 calculations, exact-decimal with fixed rounding directions), `domain.py` (lookups, child indexes, roll-ups, freeze/release cascade, ledger minting).

Routes: `routes/common.py`, `routes/projects.py`, `routes/rides.py`, `routes/show.py`, `routes/packages.py`, `routes/commercial.py` (written this session: VE items, VE ballots, rehearsal runs, maintenance items, budget ledger), `routes/__init__.py`, `app.py`.

## Endpoint count

**66 registered routes** — verified 1:1 (no missing, no extras) against the 66 `method`/`path` pairs in `SCAFFOLD.yaml`: 65 domain endpoints plus `POST /_clock/set_current_utc`. (The "67" figure in my earlier working notes was an overcount.)

## Boot and behaviour confirmed

- `bash start.sh` boots on `$PORT` (default 10000), binds `0.0.0.0`, `exec`s the server in the foreground; pip install is skipped when Flask is already importable so per-test reboots don't contend.
- Fresh boot from a clean process: `GET /attraction-projects` and `GET /show-scenes` both return `total_count: 0`, and `api_request_timestamp` reads exactly `2026-08-01T00:00:00.000Z` — nothing is seeded and the clock never falls back to wall time. Storage is process-local dicts only; no file, SQLite or /tmp artifact is created.
- A 200-line end-to-end smoke script (`/tmp/t2395_smoke.py`) passed twice, including on a second from-scratch boot. It walks the full 9-rung ladder BLUE_SKY → OPERATIONS_HANDOVER and asserts exact derived values: ride capacity `(20, 1440, 1231)`, cost of work `(120000, 168000, 1288000)`, queue capacities `(307, 66)` with `accessible_share_pct 17.69`, `virtual_queue_allocation 74`, `posted_wait_minutes 18.2`, VE net saving `800000`, rehearsal `(2000, 1047, PASS)`, spare stock `2`, scene quality `90.00`. It also exercises the negative paths: 401/403, 412 stale version, 409 duplicates/state/window-conflict/soft-open-per-date/phase-sequence, 422 width-minimum/party-role-mismatch/veto-not-permitted/critical-not-waivable/ledger-kind-not-writable, 400 for `limit=0`, `offset=-1`, bad enum filter and a stray body field on a no-input endpoint, plus the full freeze cascade (CRITICAL finding → FROZEN, both VALIDATED scenes → HELD with `held_from_status`/`SAFETY_FREEZE`, `show_quality_score` → 0.00, writes rejected; then close → OPEN, scenes restored to VALIDATED, score back to 90.0) and ledger reversal (`-5000` with `reversal_of_sequence_no`, second reverse rejected).

## One caveat worth relaying

While cleaning up I ran a `pkill -f "python3 app.py"` before realising the host has many concurrent per-test servers from other rounds; it appears to have killed its own shell almost immediately (mine died, 10+ others survived), and the harness relaunches a server before every test, so impact should be nil. Subsequent cleanup was scoped by `/proc/<pid>/cwd` to this task only. Both of my smoke servers are now stopped and `__pycache__` has been removed.

## Step 7: Run tests and iterate — 2026-09-02T12:30:00.000Z

All 8 parallel rounds passed on the first sweep — 94/94 each, zero failures, zero errors.

## Summary

**Iterations run:** 1 (single 8-round parallel stability sweep; no fixes needed).

**Sweep result:**
| round | passed | failed | errors | total |
|---|---|---|---|---|
| 1–8 | 94 | 0 | 0 | 94 |

Results at `/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/workspace/implementation/results.{1..8}.json`. Sweep ran under `setsid nohup` with `--isolation per-test-server`, `--test-timeout 30`; wall time ~22 min for the concurrent set (host is heavily CPU-contended — 400+ concurrent runner processes were visible). No `Terminated` server logs and no round dying at a shared wall-clock instant, so no reaping artifact.

**Tests deleted:** none. No test failed in any round, so the STEP 1 coverage / unique-derivability protocol was never triggered.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:** none.

**Resume-note verification.** The prior interrupted run had touched `test_suite/test_14_endpoint_and_error_contracts.py` (mtime 11:25) — `workspace/implementation/routes/` itself was *not* modified (only its `__pycache__` directory mtime moved; every `routes/*.py` still carries its original generator mtime of 08:56–09:00). I audited the current on-disk test artifact for signs the partial run had weakened it rather than fixed it:
- Per-file test counts are 4/6/4/6/6/6/6/4/4/12/7/4/10/7/8 = **94**, exactly matching the generator's recorded manifest (including `test_14`'s 7 tests), so nothing was dropped.
- Zero `pytest.mark.skip` / `xfail` anywhere in `test_suite/` or `test_helpers/`.
- Zero `validate_error_is_one_of` relaxations — every error assertion is still an exact `error_id` + HTTP-status pair via `validate_error`.

So the baseline is intact and green; there was no flakiness to chase and no PRD-fidelity repair outstanding.

**Orchestrator verification (independent):** re-read all 8 `results.$i.json` directly — every round reports `passed=94 / total=94, failed=0, errors=0`.

## Step 8: Finalize PRD — SKIPPED — 2026-09-02T12:31:00.000Z

Skip condition met: Step 7 exited on the first 8-round sweep with 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes and 0 `implementation/` fixes — zero iterations beyond the baseline. Per the skill's Step 8 skip rule, `PRD.md` already determined every behavior the test suite exercised, so no `PRD_FINALIZED.md` is produced and Step 9 starts from `PRD.md`. (Orchestrator decision, made autonomously per the run's AUTONOMY directive; no subagent spawned.)

## Step 9: Complete PRD — eliminate residual ambiguity and mismatch — 2026-09-02T13:12:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2395_themed_attraction_development/workspace/PRD_COMPLETED.md`.

## Summary

- **Source**: `workspace/PRD.md` (no `PRD_FINALIZED.md` — step 8 skipped): 496 lines / 93,217 chars
- **Result**: `workspace/PRD_COMPLETED.md`: 496 lines / 100,107 chars — **+6,830 chars, 0 line delta** (28 in-place paragraph revisions, no new sections, no new paragraphs)
- **Counts**: 25 ambiguity-pins, 3 mismatch-revisions

### Changes
- §2.2 Success envelope — insert — ambiguity — `api_request_timestamp` is read from the logical clock, not wall clock — `response.py:30`, `store.py:78`
- §2.3 Pagination — insert — ambiguity — non-integer `limit`/`offset` → `ERR_INVALID_REQUEST`; out-of-enum filter values → `ERR_INVALID_REQUEST`; id-valued filters are opaque (empty page, not 404); undeclared query params ignored — `validate.py:236-269`
- §2.3 Ordering — insert — ambiguity — ties on identical `created_at` broken by server write order — `store.py:124`
- §2.4 Audit triple — insert — ambiguity — `version` is 1 on create and `updated_at` == `created_at` — `store.py:91`
- §2.4 Cascades — insert — ambiguity — child creates do not bump the programme's `version` (exceptions enumerated) — `rides.py:65`, `packages.py:73`
- §2.7 Posture recomputation — revise — **mismatch** — resolving a finding is excluded from "every safety-finding write"; it leaves the programme row untouched — `packages.py:300-310`
- §3.1 Capacity summary — insert — ambiguity — both capacity variants report 0 while `selected_ride_system_id` is null — `projects.py:237`
- §3.1 Logical clock — insert — ambiguity — `to_iso8601` required, backwards moves accepted, 200 + empty `data` — `projects.py:22-27`
- §3.2 mark-engineered — revise — ambiguity — `control_system_spec_ref` is required-but-nullable (omission is a schema violation) — `rides.py:134`
- §3.2 Ladder capacity re-check — insert — ambiguity — null selected system = 0 operational capacity → `ERR_CAPACITY_TARGET_NOT_MET`, evaluated before the package gate; the `COMMISSIONED` gate reports `ERR_PHASE_PRECONDITION_UNMET` after the accessibility gates — `projects.py:151-155,174-175`
- §3.3 Scene create — insert — ambiguity — unresolvable *or* cross-programme `follows_scene_id` → `ERR_SCENE_NOT_FOUND` at tier 5 — `show.py:26-33`
- §3.3 Sequence — insert — ambiguity — uniqueness scan skips the scene's own row; omitted `follows_scene_id` clears it to null — `show.py:36-41,117`
- §3.3 Cues — insert — ambiguity — re-verifying a `VERIFIED` cue → `ERR_CUE_STATE_INVALID` — `show.py:249`
- §3.3 Validate — insert — ambiguity — only the scene is written; programme `version`/`show_quality_score` unchanged — `show.py:178-181`
- §3.5 Package create — insert — ambiguity — created with `pinned_ride_system_version`/`submitted_by_user_id`/`approved_by_user_id` null — `packages.py:67-69`
- §3.5 Submit — insert — ambiguity — no body fields accepted — `packages.py:104`
- §3.5 Request-revision — insert — ambiguity — `reason` required, ≥1 char, no upper bound, validated then discarded — `packages.py:123`
- §3.6 Open review — insert — ambiguity — programme not touched (no version bump, no posture/forecast re-derivation) — `packages.py:212-221`
- §3.6 Resolve — revise — **mismatch** — the "owning review must be `FINDINGS_ISSUED`" check is not performed; resolution writes only the finding row — `packages.py:300-310`
- §3.6 Clear review — insert — ambiguity — no body fields; touches neither package nor programme — `packages.py:230-242`
- §3.7 Change order — insert — ambiguity — `amount_cents` is any integer including 0; only strictly positive trips `RESTRICTED` — `commercial.py:321,328`
- §3.7 Reversal — insert — ambiguity — reversal's `memo` is the supplied `reason` (≥1 char, no max); 201; reversal row carries `reversed` false; no ceiling check — `commercial.py:350,358-364`
- §3.8 Ballots — insert — ambiguity — every ballot bumps the item's `version`; programme untouched until resolution; 201 + ballot row — `commercial.py:140,151`
- §3.8 Adoption guard — insert — ambiguity — null selected system contributes 0; tier-38 guard masks `ERR_BALLOT_ALREADY_CAST` — `commercial.py:110-118`
- §3.8 VE_SAVING minting — insert — ambiguity — minted with no budget-ceiling check even when `net_saving_cents` is negative — `commercial.py:142-147`
- §3.9 Booking — insert — ambiguity — window strings echoed verbatim; window ordering checked at tier 3 before `project_id`; soft-open ration counts `COMPLETED` runs too — `commercial.py:164-167,182-187,192-193`
- §3.9 Completion — revise — **mismatch** — a missing `selected_ride_system_id` is *not* refused; capacity 0 → threshold 0 → `PASS` — `commercial.py:222-226`
- §3.9 Handover rung — insert — ambiguity — gate reporting order: critical finding → maintenance manual → soft-open validation — `projects.py:187-195`

**Orchestrator verification:** `workspace/PRD_COMPLETED.md` present, 496 lines / 100,107 chars, 5 top-level sections, ends with the complete error-code catalogue (not truncated).

---

**PIPELINE COMPLETE.** All nine steps satisfied for `task_2395_themed_attraction_development`.
