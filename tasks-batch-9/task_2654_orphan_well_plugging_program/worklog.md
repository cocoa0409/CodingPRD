# Worklog — task_2654_orphan_well_plugging_program

## Step 1: Create task directory — 2026-09-04T01:49:00.000Z

Created /home/ubuntu/github/CodingPRD/tasks/task_2654_orphan_well_plugging_program and its workspace/ subdirectory. Index 2654 was pre-assigned by the invoking pipeline (no ./tasks/ scan performed, per orchestration instructions — 32 pipelines run concurrently on this host and auto-allocation would collide).

## Step 2: Generate scaffold — 2026-09-04T03:42:00.000Z

Scaffold generation for task 2654 is complete. All three files are written, parse cleanly, and pass the lint.

**Files** (in `/home/ubuntu/github/CodingPRD/tasks/task_2654_orphan_well_plugging_program/`)
- `SCAFFOLD.yaml` — 3124 lines (no `scaffold_difficulty_design` / `scaffold_corner_design` keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 1646 lines (single top-level key)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 4896 lines (single top-level key)

**§1.0–§1.7 counts**
15 entities (Operator, Well, ProductionRecord, OrphanDetermination, SiteAccess, WellTransfer, Contractor, Solicitation, Bid, UnitCostContract, PluggingJob, ReclamationTask, FundingSource, FundingAllocation, GrantReport) · 15 state machines (Well carries two independent dimensions) · 2 OCC concurrency rules · 8 calculations · 40 ordered validations · 58 endpoints (29 GET / 29 POST) · 51 errors · 8 roles (2 entity-backed) · profile: compliance_audit + quota_allocation, layers `optimistic_concurrency`/`cascading_side_effects`/`dual_variant_calculation`/`selector_policy`, `segregation_of_duties`, `immediate`.

**§1.8 — 9 rule ids × 2 instances = 18**
dual_variant_calc 2 · combinatorial_formula 2 · non_linear_state_machine 2 · transitive_cascade 2 · priority_pair_validation_conflict 2 · boundary_precision_check 2 · cross_entity_state_dependency 2 · resource_temporal_overlap 2 · compensating_invariant 2

**§1.9 — 84 instances (65 recipes + 19 `excluded_because` stubs)**
entities 9 (9+0) · state_machines 15 (11+4) · calculations 14 (9+5) · validations 25 (18+7) · endpoints 8 (7+1) · errors 2 (2+0) · rbac 5 (5+0) · cross_cutting_complexity_layers 5 (3+2) · consistency_model 1 (1+0). All 102 instance names unique across both files; every cited `difficulty_instance` resolves.

**Coverage-audit notes** — writing §1.9 as a §1.5/§1.4 audit surfaced and fixed eight latent SCAFFOLD.yaml defects: (1) unreachable `ERR_RECLAMATION_INCOMPLETE`; (2) permanently preempted `ERR_OPERATOR_STILL_SOLVENT` (moved to priority 39); (3) over-broad priority-40 scope; (4) ReclamationTask SM contradicting validation p52; (5) `ProductionRecord.boe` rounded per row in the endpoint side effect while the calculation requires unrounded rows summed and rounded once; (6) `FORFEIT_BOND` endpoint declaring `allowable_cost_categories = [PLUGGING]` against the Operator SM's `[PLUGGING, RECLAMATION]`; (7) `override_source_id` referenced by p22/p45/p64 with no declared semantics (now specified on the funding-commitments endpoint); (8) `CREW_DEMOB_BUFFER_DAYS` with no numeric value anywhere (now stated as 2 in both places). Error-catalog sweep: all 51 error ids are now triggered by at least one §1.8/§1.9 instance (the last four — `ERR_UNAUTHENTICATED`, `ERR_UNAUTHORIZED`, `ERR_NOT_RESOURCE_OWNER`, `ERR_STALE_WELL_VERSION` — are covered by the rbac and concurrency-layer instances). Every formula-derived assert was executed in Python first (e.g. screening 59.90 / remediation 81.00, euc 7,040,000 and 8,000,000, estimate 6,070,196, ceiling total exactly 20,000,000, waterfall ranks 1/2 with 2,000,000 + 4,070,196, forfeited-bond expiry 2036-07-29). One self-check caught mid-pass: the waterfall `waterfall_rank` for a sole contributing source is 2, not 3, because skipped sources still occupy ordered positions. No sibling task directory was read at any point.

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage line from the same run: §1.5 endpoints 58 · §1.1 entities 15 · §1.8 instances 18 · §1.9 instances 65 · calls scanned 906.)

**Orchestrator verification**: `ls -la` confirms all three files present; `yaml.safe_load` parses all three; DIFFICULTY has sole key `scaffold_difficulty_design`, CORNER has sole key `scaffold_corner_design`, and SCAFFOLD.yaml has neither.

## Step 3: Copy shared files — 2026-09-04T03:44:26.346Z

Copied ./INSTRUCTION.md to tasks/task_2654_orphan_well_plugging_program/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-09-04T03:59:00.000Z

## Deliverable
`/home/ubuntu/github/CodingPRD/tasks/task_2654_orphan_well_plugging_program/workspace/PRD.md` — **482 lines**, built incrementally (1 Write + 6 heredoc/script appends), never emitted as a single giant write.

## Sections written
- `## 1. Introduction` (3 paragraphs, domain framing as a state oil-and-gas regulator)
- `## 2. Global Specifications & System-Wide Principles` — **11 subsections**: 2.1 RBAC (8 roles, `X-User-ID`/`X-User-Role`), 2.2 API Response Structure (canonical block, verified byte-identical), 2.3 Pagination, 2.4 Row Identity/Audit Timestamps/Version Counters, 2.5 Logical Regulatory Clock, 2.6 Nested Path Resolution, 2.7 Optimistic Concurrency Control, 2.8 Cents/Scores/Rounding Discipline, 2.9 Cascade Discipline, 2.10 Order of Rule Evaluation (17-step priority ladder), 2.11 Two Independent State Dimensions on a Well
- `## 3. Business Logic & Workflows` — **9 subsections** (operator register + assurance requirement; dual-variant prioritization scoring; orphan determination review; surface access; transfers/enforcement; procurement; field operations/cost accrual; reclamation/closeout; funding waterfall + federal reporting)
- `## 4. Endpoint Definitions` — 58-row table (Method | Path | Description | Authorized Role(s))
- `## 5. Error Code Catalogue` — 51-row table (Error ID | HTTP Status Code)

## Coverage verification (all mechanical, via yaml+regex against SCAFFOLD.yaml)
| Check | Result |
|---|---|
| Endpoints | **58/58** present, section 4 table has exactly 58 rows, 0 missing |
| Error ids | **51/51** present; also **51/51** appear in the narrative, not only in the section 5 table; section 5 table has exactly 51 rows |
| Validations | **40/40** expressed (section 2.10 ladder + per-workflow prose) |
| Calculations | **8/8** expressed in precise business prose |
| State machines | **15/15**, all transitions/preconditions/side effects rendered |
| Concurrency rules | **2/2** (`expected_well_version` -> `ERR_STALE_WELL_VERSION`, `expected_operator_version` -> `ERR_STALE_OPERATOR_VERSION`, both 412) |
| Entities | 15/15 |

## Hard Contracts (transcript-only, per SKILL.md — not written into any file)
- **Contract 1 Field-Name Coverage — PASS.** 129/129 entity field names present in backticks, 0 missing. 81/81 distinct endpoint input field names present, 0 missing.
- **Contract 2 Rule Coverage — PASS.** Walked all 15 state machines, both concurrency rules, all 8 calculations, all 40 validation conditions with their error ids, every endpoint `side_effects` entry, and sibling-branch symmetry (notably the two `DEBARRED` branches: `GOOD_STANDING -> DEBARRED` stamps `suspended_at` and cascades contracts; `SUSPENDED -> DEBARRED` does neither — rendered at equal density).
- **Contract 3 section 3 Path Purity — PASS.** 1064 backtick tokens scanned inside section 3; 0 starting with `/`, 0 bare HTTP-method tokens, 0 method+path tokens.
- Fuzzy-language scan (`approximately`, `roughly`, `about N`, `~N`, etc.): 0 hits.

## Tail confirmation
`tail -30` ends at the `ERR_DISBURSEMENT_EXCEEDS_ALLOCATION` row — the final row of the completed section 5 Error Code Catalogue table. The file ends at a real section boundary, not mid-sentence. No truncation.

## Editorial decisions on scaffold-internal contradictions
- Scaffold validations reference an `X-Role` header; resolved in favour of the SKILL.md mandated `X-User-Role`.
- `POST /contractors/{id}/eligibility` role conflict (state machine `ProcurementOfficer` vs `endpoints[].roles: [ProgramAdmin]`): section 3 prose names no role; the section 4 table (generated from `endpoints[].roles`) is authoritative.
- `WellTransfer.void_reason`: wrote the state machine's literals `MANUAL_VOID`/`TRANSFEREE_INSOLVENT` as authoritative, with the supplied `rationale` accompanying the manual action.
- `GrantReport.revision_round`: increments on resubmission (`REJECTED -> SUBMITTED`), per the field description "number of completed REJECTED -> SUBMITTED cycles".

## Constraints honoured
Never opened, grepped, or referenced `SCAFFOLD_DIFFICULTY_DESIGN.yaml` or `SCAFFOLD_CORNER_DESIGN.yaml`; never read a sibling task directory; no report/summary `.md` files written.

**Orchestrator truncation check** (the known doc-generator failure mode): `wc -l` = 482, `wc -c` = 105874. `tail -20` ends on the last error-catalogue row; `grep -n '^#'` shows all five top-level sections present with section 5 last. Confirmed NOT truncated — no regeneration needed.

## Step 6: Generate implementation — 2026-09-04T04:28:00Z

**Orchestrator note — agent death and resume.** The Step 6 subagent was terminated mid-run by a transient API error ("The system encountered an unexpected error during processing"), having written 15 files / 2459 lines but NOT app.py, leaving the server unbootable (start.sh ends in `exec python3 app.py`). Rather than respawn a fresh agent — which would have rewritten the already-finished modules against a different mental model and made the implementation internally inconsistent — the orchestrator computed the exact remaining work by diffing the route table against SCAFFOLD.yaml §1.5 by path shape (30/58 routed, 28 missing) and SendMessage'd that to-do list to the SAME agent id, which resumed with its context intact. The resumed run is the summary below. It reports 21 remaining endpoints where the orchestrator computed 28; the difference is 7 endpoints the agent had already written into routes_bids.py (319 lines, present on disk but not in the pre-death file listing) — final diff is 58/58 either way.

Implementation complete. All 21 remaining endpoints plus `app.py` are written, the endpoint diff is 58/58, and an end-to-end smoke run through the full lifecycle passed.

## New files this session (all in `workspace/implementation/`)

| file | lines | endpoints |
|---|---|---|
| `routes_jobs.py` | 332 | POST /plugging-jobs, GET /plugging-jobs/{id}, GET /plugging-jobs, POST mobilize, POST field-report, POST review |
| `routes_reclamation.py` | 144 | GET /plugging-jobs/{id}/reclamation-tasks, GET /reclamation-tasks/{id}, POST /reclamation-tasks/{id}/progress |
| `routes_funding.py` | 388 | 11 endpoints: funding sources (3), funding-commitments, allocations (3), grant reports (4) |
| `routes_clock.py` | 21 | POST /_clock/set_current_utc |
| `app.py` | 90 | app factory, 11 blueprints, section 2.2 error envelope handlers, `0.0.0.0:$PORT` foreground |

Pre-existing (unchanged): `start.sh` 10, `requirements.txt` 1, `store.py` 135, `errors.py` 89, `envelope.py` 119, `auth.py` 107, `validate.py` 170, `calc.py` 568, `lookup.py` 83, `routes_operators.py` 203, `routes_wells.py` 166, `routes_determinations.py` 229, `routes_access.py` 170, `routes_transfers.py` 172, `routes_procurement.py` 237, `routes_bids.py` 319. Total 3753 lines across 19 Python modules.

## Organization
- **58 endpoints** across 11 blueprints registered in `app.py` (operators 4, wells 5, determinations 5, site access 4, transfers 4, procurement 8, bids/contracts 7, jobs 6, reclamation 3, funding 11, clock 1).
- **8 calculations** all in `calc.py` (priority scores, classification criteria, assurance requirement, bid basket/composite scoring, plugging estimate, plugging actual with per-line 4.25% fee, funding waterfall with the floor-rounded federal match cap, grant-report figures), plus the cascade helpers (`recompute_operator`, licence propagation, `refresh_source_availability`, `expire_funding_sources`).
- **40 validations**: schema layer in `validate.py`, error catalogue + HTTP mapping in `errors.py`, auth/ownership/SoD in `auth.py`, and the business/state/referential gates inline in each route in PRD section 2.10 priority order.
- **15 state machines**: one per owning route module; every touched row gets exactly one `version` bump per request.

Two ordering calls worth flagging: on mobilize I follow section 2.10 priority 15 (`ERR_CONTRACTOR_NOT_ELIGIBLE` before `ERR_CONTRACT_NOT_ACTIVE`) rather than the section 3.7 prose order, because the licence-suspension cascade would otherwise make the contractor error unreachable; and grant-report `revision_round` increments on resubmission out of `REJECTED` (PRD section 3.9) rather than on `REJECT` (scaffold side-effect list).

## Smoke test (port 8971, killed by its own PID 1425739; port confirmed free afterwards)
Booted via `PORT=8971 bash start.sh`, then drove 46 calls end to end: operator -> well (screening 78.10, remediation 91.50, idle_months 88, operator flips DELINQUENT with required_bond 1500000) -> production record -> determination create/submit/CONFIRM (well -> ORPHAN_CONFIRMED) -> site access AGREEMENT_EXECUTED -> contractor/solicitation/bid/RESPONSIVE/award -> contract ACTIVE -> job (estimate 4320000, crew_window_end_at 2026-08-16) -> mobilize -> waterfall (federal grant at rank 1 correctly throttled to 0 by a zero non-federal base, STATE_FUND at rank 2 covers 4320000) -> field report (4494218 = per-line 4.25% fee, hand-verified) -> review ACCEPT -> 3 tasks created -> `ERR_REVEGETATION_WAITING_PERIOD` 422 before the clock advance, then closeout to job RECLAIMED / well RECLAIMED -> `ERR_SEGREGATION_OF_DUTIES` 403 on self-disbursement, 200 for a different officer -> grant report DUE/SUBMITTED/REJECTED -> 404 `ERR_PLUGGING_JOB_NOT_FOUND`.

Envelope confirmed: `{"meta":{"api_request_id":"req_...","api_request_timestamp":"2026-08-01T00:00:00.000Z"},"response_type":"object","data":{...}}`; list responses add `limit/offset/total_count/has_more` to `meta`; errors use `response_type:"error"` with `data.{error_id,message}`. Clock reads exactly `2026-08-01T00:00:00.000Z` on a fresh boot.

## Verification
`python3 -m py_compile *.py` -> all 19 modules compile clean. Endpoint diff against SCAFFOLD.yaml endpoints: **58 declared / 58 routed, 0 missing, 0 extra**. Storage is in-memory dicts only, no seeding at import or boot.

## Test suite completion (queue B tail)

- `test_suite/test_17_role_scoping_and_duty_separation.py` (427 lines, 5 `Corner/rbac` tests)
- `test_suite/test_18_concurrency_layers_and_selector_order.py` (268 lines, 3 `Corner/cross_cutting_complexity_layers` tests)
- `test_suite/test_19_read_your_writes_settlement.py` (82 lines, 1 `Corner/consistency_model` test)

Final census: 101 tests, 36 tagged `Design: Difficulty/...` (18 instances x 2) and 65 tagged
`Design: Corner/...` (all 65 non-stub instances, one each). Every test carries exactly one
Design tag pointing at a live instance; the 19 corner stubs emit nothing. Recipe defects
corrected against the PRD: duplicate production month is HTTP 409 (not 422), the solicitation
lands on `EVALUATING` after `CLOSE` (not "CLOSED"), a disbursement needs a `FIELD_REPORTED`
job, and a determination create on a never-producing well leaves the well `INACTIVE` (idle
sentinel 999), not `PRODUCING`.

## Step 5: Generate unit tests — 2026-09-04T05:29:00Z

**Orchestrator note on ordering**: Steps 5 and 6 were launched concurrently in a single assistant message (giving the impl generator physical isolation from `test_suite/`, which did not exist when it started). Step 6 finished first, so its entry appears above this one; the section headed "Test suite completion (queue B tail)" at line 115 was appended by the Step 5 subagent itself mid-run, not by the orchestrator. Both are left in place — worklog is append-only.

Test infrastructure and test suite for `task_2654_orphan_well_plugging_program` are complete, at the task root (nothing written under `workspace/`).

## Files written

`test_helpers/` — 2121 lines total
`__init__.py` 1, `constants.py` 203, `api_errors.py` 127, `test_users.py` 69, `types.py` 289, `api_client.py` 355, `factories.py` 331, `assertions.py` 254, `fixtures.py` 492

`test_suite/` — `conftest.py` 19 plus 19 domain-named test modules, 6585 lines:
- Queue A (`test_01`-`test_09`): 4 tests each = **36 tests**, 183/251/239/259/192/191/204/224/291 lines
- Queue B (`test_10`-`test_19`): 9/11/9/9/9/7/2/5/3/1 = **65 tests**, 537/649/621/644/657/553/113/427/268/82 lines

## Coverage against the design indices

**101 tests: 36 queue A + 65 queue B.** A programmatic audit over both yaml files confirms:
- 18 non-stub difficulty instances, each with exactly 2 tagged tests (target >=2) — met
- 65 non-stub corner instances, each with exactly 1 tagged test (target >=1) — met
- Every test has exactly one `Design:` line, every tag resolves to a live instance in the right rule/section, no dual tags, no untagged tests, no tags on the 19 `excluded_because:` stubs (which emit nothing, as designed)
- **No instances skipped.** Every non-stub instance passed the PRD-first two-condition filter.
- No `skip`/`skipif`/`xfail` anywhere; no docstring mentions "scaffold"; every test docstring carries at least one verbatim `PRD: "..."` quote, and a citation checker over all 101 tests reports `missing=0` (every quote is a literal substring of `workspace/PRD.md`).

## Recipe defects corrected against the PRD (assertions follow the PRD, not the yaml)

- `ERR_DUPLICATE_PRODUCTION_MONTH` is HTTP **409** (PRD section 3.1), not the recipe's 422; likewise `ERR_SOLICITATION_NOT_OPEN`, `ERR_FUNDING_SOURCE_EXPIRED`, `ERR_DUPLICATE_BID`.
- A solicitation lands on **`EVALUATING`** after `CLOSE`, not the recipe's "CLOSED".
- Disbursement recipes were rebuilt to advance the job to `FIELD_REPORTED` (authorize access -> mobilize -> file report) because PRD line 350 requires it.
- `CONFIRM` recipes were rebuilt on an operator in regulatory trouble (`DELINQUENT`/`INSOLVENT`/`REVOKED`) per section 3.3.
- A determination create on a never-producing well leaves the well **`INACTIVE`** (idle sentinel 999 >= 12, section 3.2), not the recipe's "PRODUCING throughout"; the OCC point is asserted on `version`/`access_status` instead.
- Ordered-id assertions on list reads that share one logical `created_at` were changed to set comparisons (not uniquely derivable); explicit PRD orderings (production months ascending) are still asserted as sequences.
- Non-derivable operator `version` assertions in the aggregate-recompute recipe were dropped (section 2.9).
- The forfeited-bond source expiry `2036-07-29T00:00:00Z` was independently verified as clock + 3650 days.

## Verification

`python3 -m compileall test_helpers test_suite` -> clean (all 29 files compile). `ls -la` confirms `test_helpers/` and `test_suite/` at the task root and `workspace/` containing only `INSTRUCTION.md`, `PRD.md`, `implementation/` — no stray copies.

**Orchestrator verification**: `grep -c 'def test_'` across test_suite = 101 tests; `Design:` tag census = 65 Corner + 36 Difficulty = 101, matching. No test_helpers/ or test_suite/ copies found under workspace/.

## Step 7 — test/fix iteration loop (parallel 8-round stability sweeps)

**Iteration 1** — 8/8 rounds at 98/101, identical failure set (deterministic, not flaky):
- `test_08::test_notice_windows_that_merely_touch_do_conflict` — got `ERR_INVALID_STATE_TRANSITION`, expected `ERR_ACCESS_WINDOW_CONFLICT`
- `test_14::test_the_contract_ceiling_refuses_one_cent_over_and_accepts_exact_equality` — contract `CLOSED`, expected `ACTIVE`
- `test_17::test_an_operator_caller_reads_and_writes_only_its_own_wells` — foreign-well production filing returned 201

All three traced to implementation defects; no test was deleted and no test_helpers change was needed.

Fixes:
1. `routes_access.py::create_site_access` — moved the closed-notice-window overlap check ahead of the well access-dimension edge check. Every row in `CONFLICTING_STATUSES` (`REQUESTED`/`AGREEMENT_EXECUTED`/`ENTRY_ORDERED`) also holds the well out of `NO_ACCESS_REQUESTED`/`ACCESS_DENIED`, so with the old ordering `ERR_ACCESS_WINDOW_CONFLICT` was unreachable for every status PRD 3.4 names in its scan set.
2. `routes_jobs.py::_apply_contract_obligation` — gated the `ACTIVE -> CLOSED` transition behind `may_close`, passed only from `file_field_report`. PRD 3.7 attaches that transition to the field report alone; the contract-exposure paragraph governing job ordering states only the rejection rule.
3. `routes_wells.py::create_production_record` — added the `Operator`-role ownership check (PRD 3.1 "by the `Operator` itself for its own wells"; PRD 2.10 step 3 -> `ERR_NOT_RESOURCE_OWNER`).

**Iteration 2** — 8/8 rounds at 101/101. No `Terminated` in sweep.log (no reaping).

## Step 7: Run tests and iterate — 2026-09-04T05:47:44Z

All 8 rounds green. Done.

## Summary

**Iterations run:** 2 (each a parallel 8-round stability sweep, `setsid nohup`, per-test-server isolation).

**Iteration 1:** all 8 rounds 98/101 with an *identical* failure set — deterministic, not flaky, so no load-induced noise to discount.

**Tests deleted:** none. All three failures survived STEP 1a (verbatim PRD coverage) and STEP 1b (unique derivability), and STEP 2 found the fixtures/requests/assertions faithful to PRD. All three were genuine implementation defects.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `implementation/`:**

1. `workspace/implementation/routes_access.py` — `create_site_access`: moved the closed-notice-window overlap check ahead of the well access-dimension edge check. Decisive reachability argument: every site-access status PRD section 3.4 puts in the window-conflict scan set (`REQUESTED`, `AGREEMENT_EXECUTED`, `ENTRY_ORDERED`) also holds the well out of `NO_ACCESS_REQUESTED`/`ACCESS_DENIED`, so with the well gate first, `ERR_ACCESS_WINDOW_CONFLICT` was **unreachable for all three** — yet PRD names it in section 2.10 step 14 and in the error catalogue. Both the "one live request" and the `ACCESS_DENIED` waiting rules remain reachable after the reorder (a fully-elapsed prior window yields no conflict, so the state gate fires).

2. `workspace/implementation/routes_jobs.py` — `_apply_contract_obligation`: the `ACTIVE -> CLOSED` transition is now gated behind a new `may_close` flag, passed only from `file_field_report`. PRD section 3.7 attaches that transition to the field report alone ("If it lands exactly on `ceiling_cents`, the contract transitions `ACTIVE -> CLOSED`"); the contract-exposure paragraph governing job ordering states only the rejection rule, and section 3.6 defers to "**the** route into `CLOSED`" (singular). Closing on a job order was a side effect with no verbatim PRD sentence behind it. Verified no other test reaches `CLOSED` (test_05/test_13 use `SUSPENDED` contracts).

3. `workspace/implementation/routes_wells.py` — `create_production_record`: added the missing `Operator`-role ownership check. PRD section 3.1 states production is filed "by the `Operator` itself **for its own wells**", and section 2.10 step 3 maps an Operator-scoped caller reaching outside its own data to `ERR_NOT_RESOURCE_OWNER`. (Section 2.1's "five operations" list omits this endpoint, but that list is already non-exhaustive as a rejection enumeration — it includes the well *list*, which narrows rather than refuses — and no other error fits PRD's explicit "for its own wells" constraint.)

**Final per-round results (iteration 2):** rounds 1-8 all **101/101**. `sweep.log` contained zero `Terminated` occurrences, confirming no round was reaped.

**Orchestrator verification** (per the known failure mode where a Step 7 agent claims a clean sweep with no artifacts behind it): the orchestrator independently `json.load`ed all 8 `workspace/implementation/results.$i.json` files and confirmed `passed == total == 101` in every one, with fresh mtimes; `grep -c Terminated workspace/sweep.log` = 0. Step 8 is REQUIRED (3 implementation fixes > 0), not skipped.

## Step 8: Finalize PRD — 2026-09-04T05:51:00Z

Done. Created `workspace/PRD_FINALIZED.md`.

## Line counts
- `PRD.md`: 482 lines
- `PRD_FINALIZED.md`: 484 lines (+2 lines, **+0.41%**); 3 edits total (1 new paragraph, 2 in-place sentence revisions)

## Changes
- **Section 2.1 "Ownership violations"** — revise — de-counted the closed "Five operations ... all five" enumeration to an open "Several operations ... every such rejection", added *the filing of a production record against a well* and *the submission of a bid* to the list, and extended the `Contractor` clause to cover the `contractor_id` supplied on a bid submission — `implementation/routes_wells.py:128-129` (new check), `routes_bids.py:48-50`
- **Section 3.4 "Window conflicts"** — insert (one paragraph) — pins that the `ERR_ACCESS_WINDOW_CONFLICT` scan runs *before* the three well-access-dimension gates (well edge, one-live-request, `ACCESS_DENIED` waiting rule), that those three report `ERR_INVALID_STATE_TRANSITION`, that they fire in that order, and why (the well is a merely referenced row, so section 2.10 step 10 does not reach it; otherwise the conflict error is unreachable) — `implementation/routes_access.py:53-85`
- **Section 3.7 "Contract exposure"** — revise — pins that an order landing exactly on `ceiling_cents` is accepted and never changes the contract's `status`; the sole route into `CLOSED` is the field report — `implementation/routes_jobs.py:49-62, 157, 283`

## Per-edit pre-edit search log

**Edit 1 — section 2.1 ownership enumeration**
- (a) Subject: every site that raises `ERR_NOT_RESOURCE_OWNER`, and the entity-backed comparison rule behind each.
- (b) Enumerated: `grep -rn "not_owner\|NOT_RESOURCE_OWNER" *.py` -> `auth.py:90` (factory), `routes_wells.py:89` (fetch_well), `routes_wells.py:103` (list_wells, filter-mismatch form), `routes_wells.py:129` (create_production_record — the Step 7 site), `routes_bids.py:50` (create_bid, supplied `contractor_id`), `routes_bids.py:127` (fetch_bid), `routes_bids.py:140` (list_bids), `routes_jobs.py:244` (file_field_report). Also swept for un-enforced `Operator`/`Contractor` paths that must *not* be claimed: `fetch_operator` (section 4 authorizes `Operator`) has **no** ownership check, `list_production_records` has **no** ownership check, `propose_transfer` (`Operator` authorized) has **no** ownership check. `routes_procurement.py` imports `not_owner` but never raises it.
- (c) Adjustment: the impl has **seven** enforcing sites, not the six a naive "add production records" patch would imply. Rather than restate a hard count (which would falsely exclude bid submission, or falsely imply the un-enforced operator-fetch / production-list / transfer-proposal paths were covered), I replaced the count with "Several ... every such rejection" and listed all seven explicitly. The `Contractor` clause was widened with "the `contractor_id` it supplies on a bid submission" so the newly listed bid-submission case is described correctly (it compares a *body* field, not a stored row's field).

**Edit 2 — section 3.4 check ordering on site-access create**
- (a) Subject: the order of gates inside site-access creation, and the error identity of the well-access-dimension gates.
- (b) Enumerated: `routes_access.py:34-105` full `create_site_access` body (decorator auth -> `get_well` -> `v.body()` schema -> window-conflict loop over `CONFLICTING_STATUSES` -> well `access_status` edge -> live-`REQUESTED` scan -> `ACCESS_DENIED` window-elapsed scan -> insert -> mirror well to `ACCESS_PENDING`); `routes_access.py:131-175` `resolve_site_access` (its own `bad_transition` gates plus `ERR_STATUTORY_NOTICE_PERIOD_ACTIVE` — untouched by the new wording); `grep -rn "access_status" *.py` -> `routes_wells.py:69` (initial value), `routes_wells.py:98/111` (list filter), `routes_access.py:102/163/167/170` (the only writers), `routes_jobs.py:205` (mobilize's `ERR_SITE_ACCESS_NOT_AUTHORIZED` gate); sections 2.10 steps 10/12/14 and 2.11's "only one operation reads across the two dimensions".
- (c) Adjustment: scoped the new paragraph strictly to "On this create" and anchored it on section 2.10's own "merely referenced entity is never judged here" carve-out, so it does not re-order anything in `resolve_site_access`, does not touch mobilize's separate safety gate, and does not contradict section 2.10's global step 10 -> step 14 sequence (the *created* SiteAccess row is still what step 10 judges). Also stated the three gates' order explicitly rather than asserting a single merged gate, matching the three separate `bad_transition` raises.

**Edit 3 — section 3.7 no contract close on job order**
- (a) Subject: every write that can set or read a `UnitCostContract.status` of `CLOSED`, plus the shared obligation-writer.
- (b) Enumerated: `grep -rn "CLOSED" *.py` -> the **only** assignment is `routes_jobs.py:61`, gated on `may_close`; `_apply_contract_obligation` callsites `routes_jobs.py:157` (create_job, `may_close` defaulted false) and `routes_jobs.py:283` (file_field_report, `may_close=True`); `calc.py:346 contract_obligation_cents` and `routes_jobs.py:226 _obligation_with_actual` (the two greater-of computations, neither of which touches status); contract creation at `routes_bids.py:285` (`obligated_cents` 0, status `ACTIVE`); the licensing cascade `routes_procurement.py:104/112/119` -> `calc.suspend_contractor_contracts` / `restore_contractor_contracts`, which move only `ACTIVE <-> SUSPENDED` and contain no `CLOSED` reference; the `ERR_CONTRACT_NOT_ACTIVE` readers at `routes_jobs.py:119` (order), `:217` (mobilize), `:259` (field report); section 3.6's existing "The route into `CLOSED` is described in section 3.7."
- (c) Adjustment: wrote "ordering a job never changes the contract's `status`" rather than "the contract stays `ACTIVE`", because a job may legitimately be ordered only against an `ACTIVE` contract but the obligation writer is shared with the field-report path; and used "the **sole** route into `CLOSED`" to stay aligned with section 3.6's already-singular phrasing without implying the licensing cascade can reach or leave `CLOSED`.

**Orchestrator verification**: `diff PRD.md PRD_FINALIZED.md` confirms exactly 3 hunks, all inline (no new sections), 484 vs 482 lines.

## Step 9 orchestration decision (orchestrator, not a subagent)

Step 9 is run as **three sequential file-partitioned passes** over a single shared `PRD_COMPLETED.md`, rather than one subagent scanning all 19 implementation modules. Rationale: a single-shot full scan of a 3753-line implementation against a 484-line PRD reliably exhausts the agent's working budget partway and returns a `PRD_COMPLETED.md` byte-identical to its input — i.e. a scan that never actually ran. Partitioning by implementation module bounds each pass's reading set and makes non-completion detectable (each pass must move the byte count or explicitly justify zero edits for its own partition). Pass 1 performs the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edit the same file in place.
- Pass 1 (globals + operator/well spine): app.py, envelope.py, errors.py, auth.py, store.py, validate.py, lookup.py, routes_clock.py, routes_operators.py, routes_wells.py
- Pass 2 (determinations, access, transfers, procurement, bids): routes_determinations.py, routes_access.py, routes_transfers.py, routes_procurement.py, routes_bids.py
- Pass 3 (jobs, reclamation, funding, all calculations): routes_jobs.py, routes_reclamation.py, routes_funding.py, calc.py

## Step 9: Complete PRD — 2026-09-04T06:35:00Z

Run as three sequential file-partitioned passes over one shared `workspace/PRD_COMPLETED.md` (see the Step 8 entry for the rationale and the partition map). Pass 1 performed the `cp` from `PRD_FINALIZED.md`; passes 2 and 3 edited in place. Total **49 edits** (33 ambiguity-pins, 12 mismatch-revisions, plus 4 counted across both categories at shared sites), all in-paragraph — line count never moved off 484, so no section was added.

### Pass 1 — globals + operator/well spine (app/envelope/errors/auth/store/validate/lookup/clock/operators/wells)
484 lines / 107,102 chars -> 484 lines / 111,904 chars (+4,802). 14 ambiguity-pins, 2 mismatch-revisions, 16 lines across 15 hunks.
- **2.1** revise — entity-backed roles must send `X-User-ID` on *every* endpoint; both headers whitespace-stripped, empty/whitespace-only counts as absent — `auth.py:60-78`
- **2.1** insert — the server never resolves an entity-backed `X-User-ID` to a row: a bogus id yields no 404, it only fails ownership comparisons — `auth.py:68-78`
- **2.1** insert — the seven-endpoint ownership enumeration is exhaustive; single-operator fetch and a well's production-record list apply no ownership test — `routes_operators.py:56-59`, `routes_wells.py:162-165`
- **2.2** revise — `api_request_id` is `req_` + exactly 20 chars from `A-Z0-9` — `envelope.py:10,18-19`
- **2.2** revise — `api_request_timestamp` reads the logical clock, not wall time — `envelope.py:22-26`
- **2.3** insert — non-integer `limit`/`offset` and negative `offset` are `ERR_INVALID_REQUEST`; empty-string param = absent; undeclared params ignored; filters are exact case-sensitive string equality; `min_screening_score` parsed as a decimal — `envelope.py:76-119`
- **2.3** insert — ties on the ordering key resolve to insertion order; row `id` is never part of any ordering — `store.py:130-135`
- **2.4** insert — client timestamps accept trailing `Z` or an explicit offset, read naive values as UTC, normalise to UTC; non-string/unparseable -> `ERR_INVALID_REQUEST` — `store.py:74-84`, `validate.py:131-140`
- **2.5** insert — the clock may be set backwards; the instant is assigned unconditionally and reversing it undoes nothing — `routes_clock.py:13-21`
- **2.8** insert — two-decimal values and the unrounded row-level `boe` serialize as JSON numbers, never strings — `store.py:107-116`
- **2.10 step 3** insert — path `{id}` rows resolve *before* the ownership test (a scoped caller naming a nonexistent id gets 404, not 403); body-borne ownership tests still precede step 6 — `routes_wells.py:86-89`
- **2.10 step 7** insert — strict typing, zero coercion (numeric-as-string rejected, fractional int rejected, bool never a number); explicit `null` = omitted; undeclared keys ignored; strings stored verbatim but empty/whitespace fails where non-empty is required; absent body = empty object, non-object JSON body = `ERR_INVALID_REQUEST` — `validate.py:17-49,61-78`
- **3.1** revise — `spud_year` is any integer; no calendar range enforced — `routes_wells.py:38`
- **3.1** insert — an `Operator`-role caller's well list is implicitly scoped to its own wells when `operator_id` is omitted — `routes_wells.py:101-104`
- **3.5** revise — **mismatch** — `DECLARE_INSOLVENT` hop 4: PRD described only `ACTIVE -> DELINQUENT`; impl's recompute also applies the symmetric `DELINQUENT -> ACTIVE` cure, and the insolvent operator itself is exempt from both — `calc.py:240-262`, `routes_operators.py:157-163`
- **3.5** insert — **mismatch** — `FORFEIT_BOND`: already-forfeited and zero-bond refusals both report `ERR_INVALID_STATE_TRANSITION` (409) — `routes_operators.py:176-180`
- **5** insert — `ERR_NOT_FOUND` (404) for an unmounted path and `ERR_METHOD_NOT_ALLOWED` (405) for an unsupported method sit outside the business catalogue; trailing slashes ignored — `app.py:43,54-65`

### Pass 2 — determinations, access, transfers, procurement, bids
484 lines / 111,904 chars -> 484 lines / 117,898 chars (+5,994). 13 ambiguity-pins, 5 mismatch-revisions.
- **2.6** revise — **mismatch** — deleted "the contract-ceiling context on solicitation creation" from the body-foreign-key list; `POST /solicitations` resolves no foreign key — `routes_procurement.py:128-151`
- **3.3** revise — opening a determination advances the well's `version` exactly once (the `PRODUCING -> INACTIVE` reclassification does not stack a second bump); the owning operator is untouched — `routes_determinations.py:77-83`
- **3.3** insert — a non-author submission is `ERR_INVALID_STATE_TRANSITION` (409), tested after the status gate and before the revision ceiling — `routes_determinations.py:117-132`
- **3.3** insert — the `CONFIRM` operator-standing precondition reports `ERR_INVALID_STATE_TRANSITION` (409) despite the operator being a referenced row, and precedes the numeric criteria — `routes_determinations.py:174-179`
- **3.3** insert — on a passing confirmation the live `idle_months` and `cumulative_boe_60mo` are written back onto the well; `screening_score` is read as stored, never recomputed — `routes_determinations.py:180-191`
- **3.3** insert — all well/operator effects of `CONFIRM`/`REJECT` are conditional on the well still standing at `ORPHAN_CANDIDATE` (two determinations on one well can both reach `SUBMITTED`) — `routes_determinations.py:213-227`
- **3.3** insert — determination list filters (`status`, `limit`, `offset`) — `routes_determinations.py:94-107`
- **3.4** insert — only `ORDER_ENTRY` stores `legal_authority_citation`; on the other two outcomes it is still type-checked as a non-empty string then discarded — `routes_access.py:136-171`
- **3.5** insert — `decided_by_user_id`/`approved_at`/`voided_at`/`void_reason` begin null; no well-state gate and no one-live rule at proposal time — `routes_transfers.py:43-73`
- **3.5** revise — **mismatch** — `rationale` is accepted (empty string included) but never persisted on any of the three actions — `routes_transfers.py:110`
- **3.5** revise — **mismatch** — approval's transferee gate is the **full** failing-transferee test (revoked, insolvent, or delinquent-with-orphan-candidates), not just `INSOLVENT`/`REVOKED`; conditions reordered to impl order with the closure refusal pinned to `ERR_INVALID_STATE_TRANSITION` — `routes_transfers.py:116-132`
- **3.5** insert — the void closure refusal is `ERR_INVALID_STATE_TRANSITION`; a manual void overwrites `decided_by_user_id`, the insolvency cascade leaves it untouched — `routes_transfers.py:152-165`
- **3.5** insert — a proposal into the well's current operator is never refused, and when both sides name one operator that row is recomputed twice, so its `version` advances by two — `routes_transfers.py:140-141,169-170`
- **3.6** insert — duplicate `license_number` is `ERR_INVALID_REQUEST`, checked after every other input validates — `routes_procurement.py:53-56`
- **3.6** insert — the passed-deadline refusal on `OPEN` is `ERR_INVALID_STATE_TRANSITION` (409), not `ERR_BID_DEADLINE_PASSED` — `routes_procurement.py:192-196`
- **3.6** insert — **mismatch** — pinned `REOPEN` gate order (EVALUATING -> responsive-bid -> reopen ceiling -> missing `new_bid_due_at` -> clock comparison); the conditional `ERR_INVALID_REQUEST` for a missing `new_bid_due_at` is reported *after* the state and limit gates, contrary to section 2.10's step-7 precedence — `routes_procurement.py:202-225`
- **3.6** insert — `Contractor`-role bid list is implicitly scoped to its own bids; a foreign `contractor_id` filter is `ERR_NOT_RESOURCE_OWNER` — `routes_bids.py:138-141`
- **3.6** insert — `reason` stays optional on `NONRESPONSIVE`; a solicitation outside `OPEN`/`EVALUATING` reports `ERR_INVALID_STATE_TRANSITION`, not `ERR_SOLICITATION_NOT_OPEN` — `routes_bids.py:161,171-175,200-206`
- **3.6** insert — **mismatch** — on evaluation the gates run technical score -> ceiling -> licensing standing, so `ERR_CONTRACTOR_NOT_ELIGIBLE` lands after both numeric gates rather than in its section 2.10 step-15 position — `routes_bids.py:176-192`
- **3.6** insert — award eligibility is tested on the top-ranked candidate only and only after ranking (no fall-through to the runner-up); the rejection persists nothing — `routes_bids.py:252-259`

### Pass 3 — jobs, reclamation, funding, all calculations
484 lines / 117,898 chars -> 484 lines / 122,944 chars (+5,046). 10 ambiguity-pins, 5 mismatch-revisions, 15 edit sites.
- **3.2** revise — **mismatch** — replaced the recomputation enumeration with the four sites impl actually recomputes both scores at (well creation, `PRODUCING -> INACTIVE` on determination open, promotion on submit, revoke/forfeit cascade; `remediation_score` alone on `CONFIRM`), stating that a production filing recomputes only the criteria figures and that `PLUGGING_SCHEDULED`/`PLUGGED`/`RECLAIMED` recompute neither — `calc.py:137`, `routes_wells.py:156`, `routes_determinations.py:32,82`, `calc.py:544`
- **3.7** insert — body FKs on job order resolved left to right, `well_id` before `contract_id` — `routes_jobs.py:71-74`
- **3.7** revise — **mismatch** — mobilization gates reordered to contractor licence (`ERR_CONTRACTOR_NOT_ELIGIBLE`, 422) *then* contract `ACTIVE` — `routes_jobs.py:212-218`
- **3.7** insert — field-report quantities are integers >= 0 (not strictly positive); only the outer `plug_intervals` array is validated, element shape stored verbatim — `routes_jobs.py:247-251`
- **3.7** insert — review `findings` is required and non-empty but retained on no row — `routes_jobs.py:294`
- **3.8** revise — `notes` must be non-empty when supplied, is stored on all three actions (not just `START`), and is never cleared when omitted — `routes_reclamation.py:59-61,91,106,125`
- **3.8** revise — **mismatch** — closeout also recomputes `orphan_candidate_count` (a value no-op on this hop) — `routes_reclamation.py:142`
- **3.9** revise — `allowable_cost_categories` must be a non-empty array — `routes_funding.py:53`
- **3.9** insert — a `bond_operator_id` naming no operator -> `ERR_OPERATOR_NOT_FOUND` ahead of schema; a source registered with an already-past `expires_at` is still created `ACTIVE`; which gates read `expires_at` vs `status` — `routes_funding.py:46-47,36-37,257`
- **3.9** insert — commitment places no precondition on the job's `status`, and repeat passes on one job are not prevented — `routes_funding.py:120-134`
- **3.9** revise — **mismatch** — `funded_cents` is recomputed from scratch (equals the estimate after one pass, twice it after two), and the 201 array payload's `meta` omits `limit`/`offset`/`total_count`/`has_more` — `routes_funding.py:192,195`, `envelope.py:43-50` **(deferred item 2, resolved)**
- **3.9** insert — an override source failing any non-expiry, non-bond eligibility test empties the pool -> `ERR_FUNDING_SHORTFALL`, never the match error — `routes_funding.py:147,156-167`
- **3.9** revise — `invoice_cents` is an integer >= 0, and the SoD test runs ahead of both schema validation and the `COMMITTED` precondition — `routes_funding.py:232-239`
- **3.9** revise — **mismatch** — dropped "is performed by a `FundingOfficer`" from submission — `routes_funding.py:356`
- **3.9** revise — a decision supplying no `reviewer_note` writes it back to null; a note on `SUBMIT` is validated then discarded; the two roles are not split per action and no SoD applies — `routes_funding.py:362-386`

### Deferred item 1 (section 3.2 recomputation claims) — resolved by pinning, not softening
The four score inputs (`methane_scfd`, `groundwater_depth_ft`, `population_within_1000ft`, `surface_disturbance_acres`) are written only at `routes_wells.py:63-66` and mutated by no endpoint, so pass 3 stated both facts safely: exactly where impl recomputes, *and* that every recomputation necessarily reproduces the creation-time pair, making both scores fixed for a well's life. Strictly stronger than softening; removes the two literally-false clauses ("when a production month is filed against it", "on every transition of the well's `status` dimension"). Passes 1 and 2 had each deferred this as unobservable rather than risk a cross-partition contradiction.

### Orchestrator final verification
- `cmp PRD_FINALIZED.md PRD_COMPLETED.md` -> **differs** (the byte-identical no-op failure mode did NOT occur). 43 diff hunks, +15,842 chars over `PRD_FINALIZED.md`, line count steady at 484 (all edits in-paragraph, no new sections).
- Structure intact: 5 top-level sections, **58** endpoint rows, **51** error-catalogue rows, file ends on the final catalogue row — a real section boundary, not mid-sentence.
- `find workspace/implementation -name '*.py' -newermt '2026-09-04 05:41'` -> **empty**: no Step 8/9 pass touched the implementation, so the Step 7 artifacts (`results.1..8.json`, all 101/101) remain valid for the final code base.

## Pipeline complete
All nine steps finished. Final state: 15 entities / 58 endpoints / 51 errors; 101 tests, 0 deleted, 8/8 sweep rounds at 101/101; PRD.md 482 lines -> PRD_FINALIZED.md 484 -> PRD_COMPLETED.md 484 lines / 122,944 chars.
