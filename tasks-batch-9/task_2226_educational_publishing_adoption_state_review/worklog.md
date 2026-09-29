# Worklog — task_2226_educational_publishing_adoption_state_review

## Step 1: Create task directory — 2026-09-01T07:31:07.842Z

Created `tasks/task_2226_educational_publishing_adoption_state_review/` and `tasks/task_2226_educational_publishing_adoption_state_review/workspace/`.

## Step 2: Generate scaffold — 2026-09-01T09:02:49.913Z

Scaffold generation for task 2226 is complete and the lint is clean.

## Lint verdict (verbatim)

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
============================================================
  SCAFFOLD:           tasks/task_2226_educational_publishing_adoption_state_review/SCAFFOLD.yaml
  Difficulty design:  tasks/task_2226_educational_publishing_adoption_state_review/SCAFFOLD_DIFFICULTY_DESIGN.yaml
  Corner design:      tasks/task_2226_educational_publishing_adoption_state_review/SCAFFOLD_CORNER_DESIGN.yaml

Coverage
  §1.5 endpoints declared:    57
  §1.1 entities declared:     14
  §1.8 instances scanned:     25
  §1.9 instances scanned:     52
  Calls scanned (§1.8+§1.9):  971

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Files written

- `SCAFFOLD.yaml` (§1.0–§1.7 only; neither design key present)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (single key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` (single key `scaffold_corner_design`)

No sibling task directory was listed, globbed, grepped or read at any point.

## Counts

| Table | Count |
|---|---|
| §1.1 entities | 14 (StateProfile, StateStandard, AdoptionCycle, Title, AncillaryBundle, ContentEdit, Submission, CorrelationEntry, PublicComment, CommitteePanel, PresentationSlot, CommitteeVote, PricingProposal, DistrictOrder) |
| §1.2 state machines | 8 (+ 2 §1.2.1 concurrency rules) |
| §1.3 calculations | 7 (2 of them dual-variant) |
| §1.4 validations | 66 prioritized rules |
| §1.5 endpoints | 57 |
| §1.6 errors | 66 |
| §1.7 RBAC roles | 8 |
| §1.8 instances | 25 across all 9 difficulty rules (2/3/3/3/3/4/3/2/2) |
| §1.9 instances | 80 across all 9 sections — 52 with full `test_recipe`, 28 `excluded_because` stubs pointing at §1.8 instances |

Profile: `difficulty_level: expert_plus`, archetypes compliance_audit + multi_party_negotiation, layers `optimistic_concurrency`, `cascading_side_effects`, `dual_variant_calculation`, `version_pinning_on_approval`, `state_machine_shape: parallel`, `role_model: segregation_of_duties`, `consistency_model: immediate`.

## Key findings from this pass

- **All 66 error codes are now provably reachable.** An audit script found 42 unreferenced codes mid-pass; the `errors` (17 instances), `rbac` (5) and `cross_cutting_complexity_layers` (5) sections closed every one — final audit prints `66 errors, 0 uncovered`.
- **Two reachability holes in §1.4/§1.5 were fixed by feeding the audit back into SCAFFOLD.yaml** (the §1.9 ladder's rung 2, "add a real business field/endpoint"):
  - `ERR_CONTRACT_LOCKED` was unreachable, because `contract_locked` was only set at adoption, and an ADOPTED submission is already blocked earlier by priority 20. Fix: `POST /district-orders/{id}/confirm` now locks an APPROVED `pricing_proposal_id`, so a live FILED submission can own a frozen filing (three edits: field description, `QUOTED -> CONFIRMED` side effect, endpoint side effect).
  - `ERR_PANEL_CAPACITY_EXCEEDED` was unreachable until `CommitteePanel.slot_minutes_capacity` became an optional sub-session cap.
- Two assert/capture mismatches were caught before linting: `AdoptionCycle` has `submission_count` (not `filed_submission_count`) and `status` with value `OPEN` (not `phase`/`OPEN_FOR_SUBMISSION`).
- Every numeric assertion in §1.8/§1.9 is an author-computed literal derived from the scaffold's own formulas (coverage 70.00/40.00/100.00/0.00, effective weights 2.80/5.00, tally ratios 0.5000/0.8750, freight 2700/5400, TCV 365400, compliance 80/95, page budget 380/4, panel capacity 60 vs 90), and all long chains share one clock ladder (create 2026-08-01 → 2026-09-15 OPEN → file → panel/slot → 2026-10-16 two advances → 2026-10-20T14:00 open-session/present/vote/tally).

## Step 3: Copy shared files — 2026-09-01T09:02:49.913Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T09:19:16.329Z

All three Hard Contracts audited and passing. PRD written.

## What was produced

`workspace/PRD.md` — **508 lines**, ending at §5 with no audit footer.

**Structure** (11 §2 subsections, 9 §3 subsections — both domain-derived, not copied from the example):

- §1 Introduction — adoption-cycle framing, plus the two themes that generate most cascades (content-revision *pinning*, *segregation of duties*)
- §2: 2.1 Role-Based Access Control · 2.2 API Response Structure (pasted byte-for-byte from `section-2.2-response-structure.md`, verified) · 2.3 Pagination · 2.4 Identity, Timestamps and Record Versions · 2.5 The Logical Adoption Clock · 2.6 Validation Order and Nested Addressing · 2.7 Cascading Consistency · 2.8 Stale-Version Protection · 2.9 Numeric Precision and Rounding · 2.10 Conserved Quantities · 2.11 Digital Platform Commitments
- §3: 3.1 States, Frameworks and the Adoption Calendar · 3.2 Catalog, Bundles and Inventory · 3.3 Content Editing and the Revision Cascade · 3.4 Correlation Evidence and Sampling · 3.5 Filing and Withdrawal · 3.6 Pricing and Contract Terms · 3.7 Public Comment and the Compliance Score · 3.8 Panels, Slots, Ballots and the Tally · 3.9 District Sales
- §4: 4-column table, all **57** endpoints (method/path/roles verified equal to scaffold, no extras, no omissions)
- §5: 2-column table, all **66** error IDs with HTTP statuses verified against the scaffold

## Contract 1 — Field-Name Coverage: PASS

```
Field coverage check:
- entities[].fields: 163 required, 163 present, 0 missing
- endpoints[].request_body: 86 required, 86 present, 0 missing
- endpoints[].query_params: 27 required, 27 present, 0 missing
- endpoints[].path_params: 2 required, 2 present, 0 missing
Status: PASS
```
Second pass (stricter): all 163 field names and all 100 distinct endpoint input identifiers also appear in the §1–§3 narrative, not only inside the §4/§5 tables.

## Contract 2 — Rule Coverage: PASS

```
Rule coverage check:
- validations[] with priority: 66 checked, 66 expressed in prose in exact priority order, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_submission_version / expected_panel_version + error_id all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 7 checked, 7 fully expressed (all 22 named constants present verbatim), 0 missing
- validations[] conditions: 66 checked, 66 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 side-effect sets + 66 applies_to scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 163 checked, defaults/ranges/uniqueness/enum members reconstructible from prose, 0 missing
- sibling-branch symmetry: 16 groups checked, 16 with equal prose density, 0 asymmetric
Status: PASS
```
No-pseudocode audit also clean: zero occurrences of `>=`, `<=`, `+=`, `-=`, `==`, `->`, `min(`, `round(`, `clock_now`, `IN {` outside fenced blocks, and zero fuzzy quantifiers.

## Contract 3 — §3 Path Purity: PASS

```
Path purity check (§3 only):
- backtick tokens scanned: 1006
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

## One scaffold gap worth flagging

The `DECIDED → ARCHIVED` precondition in the scaffold reads `clock_now >= adoption_decision_at + ARCHIVE_DELAY_DAYS days`, but **`ARCHIVE_DELAY_DAYS` has no numeric value anywhere in SCAFFOLD.yaml** (grep confirms it appears exactly once, at line 1022, with no constants block). A symbolic-only rule is not implementable and would fail the reconstruction test, so §3.1 pins it as **30 calendar days**. If the intended value differs, that is the single number in the PRD that needs correcting — everything else is sourced directly from the scaffold. (`MAX_REVISION_ROUNDS` = 3 and `CONDITIONS_WEIGHT` = 0.5 were both resolvable and are stated correctly; `api_prefix` is empty, so the PRD notes paths are mounted at the service root.)

The two withheld design files were not opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T09:58:41.535Z

All nine queue A files are now on disk and the whole suite verifies clean.

## Files written

**Infrastructure** — `test_helpers/`
`__init__.py`, `api_client.py`, `api_errors.py`, `assertions.py`, `constants.py`, `factories.py`, `fixtures.py`, `test_users.py`, `types.py` (plus `test_suite/conftest.py`)

Two late corrections to the infrastructure:
- `constants.py`: `REVISION_PLAN_CANCEL = "CANCEL"` → `REVISION_PLAN_CANCEL_PLAN = "CANCEL_PLAN"` (PRD §3.2 names the action `CANCEL_PLAN`); dropped `ACCESSIBILITY_WCAG_2_0_AA`, `ROSTERING_CLEVER`, `ROSTERING_CLASSLINK` (not in the PRD §2.11 enumerations) and added `ROSTERING_CSV_MANUAL`; `ACCESSIBILITY_RANK` re-based to the PRD's two-level ladder. No test referenced the removed names.
- `fixtures.py`: added `seed_companion_filed_submission(api, world, isbn_base, …)` — a second released edition filed in the same cycle without clobbering `world.submission_id`, needed by the buffered-slot-conflict pair.

**Queue A (depth, §1.8)** — 9 files, 50 tests
`test_01_dual_variant_calculations.py` 4 · `test_02_combinatorial_formulas.py` 6 · `test_03_non_linear_state_machines.py` 6 · `test_04_transitive_cascades.py` 6 · `test_05_validation_priority_conflicts.py` 6 · `test_06_boundary_and_precision.py` 8 · `test_07_cross_entity_state_dependencies.py` 6 · `test_08_resource_and_temporal_overlap.py` 4 · `test_09_compensating_invariants.py` 4

**Queue B (breadth, §1.9)** — 10 files, 64 tests
`test_10_entity_corners.py` 9 · `test_11_state_machine_corners.py` 8 · `test_12_calculation_corners.py` 4 · `test_13_validation_corners.py` 3 · `test_14_endpoint_corners.py` 2 · `test_15_error_corners.py` 23 · `test_16_error_corners_continued.py` 6 · `test_17_rbac_corners.py` 5 · `test_18_cross_cutting_corners.py` 3 · `test_19_consistency_model_corners.py` 1

## Instances skipped

**None.** All 25 difficulty instances and all 52 non-stub corner instances passed the PRD-first two-condition filter. The 28 corner instances carrying `excluded_because` (the stubs) received no tests, as required.

## Verification run over the emitted suite

- `pytest --collect-only`: **114 tests** collected, zero errors.
- Every double-quoted fragment in every docstring was matched (whitespace-normalised) against `workspace/PRD.md`: **0 non-verbatim quotes**.
- Exactly one `Design:` line per test, always the docstring's last line, and every tag resolves to a real instance name: **0 untagged, 0 dual-tagged, 0 dangling**.
- Coverage audit: 25/25 difficulty instances with ≥2 tests each; 52/52 non-stub corner instances with ≥1; 0 tests pointing at a stub.
- `pyflakes` clean apart from the prescribed unused `pytest` imports; every `test_helpers` import, every `api.*` method, every `fixtures.*`/`factories.*` attribute and every keyword argument was resolved against the real signatures.

Two judgement calls worth relaying: `ERR_FOCUS_STANDARD_UNCOVERED` (queue B) is reached via a state declaring no required topics rather than through an applied `ADD_REQUIRED_TOPIC` edit, because §3.3 hop two leaves a still-`DRAFT` submission's `missing_required_topic_count` unspecified; and pinned assertions were limited to values the PRD uniquely derives — e.g. `filed_at is None` before filing and the sampling-shipment endpoint's exact 2xx code are asserted nowhere.

## Step 6: Generate implementation — 2026-09-01T09:58:41.535Z

Implementation complete and verified.

## Files written — `workspace/implementation/`

**Infrastructure**
- `start.sh` (executable) — `cd`s to its own dir, installs Flask only if missing, `exec python3 app.py`, honours `$PORT` (default 10000)
- `requirements.txt` — `flask>=3.0`
- `app.py` — app factory, blueprint registration, `ApiError` → envelope handler, 400/404/405/415/`Exception` envelope handlers, binds `0.0.0.0:$PORT`

**Core modules**
- `db.py` — in-memory dict store, logical clock (default `2026-08-01T00:00:00Z`), UUID/seq minting, `touch`/`apply_changes` (dirty-checked version bumps), `ordered`
- `errors.py` — all 67 error IDs → HTTP status, `ApiError`, `fail()`
- `response.py` — `{meta, response_type, data}` envelope; list meta adds `limit/offset/total_count/has_more`
- `middleware.py` — `X-User-ID`/`X-User-Role` auth (401), role authz (403), `StateAdoptionOfficer` state scope (403)
- `validation.py` — every enum tuple + typed field extractors, all shape failures → `ERR_INVALID_REQUEST`
- `calc.py` — the 7 calculations at `prec=80` / ROUND_HALF_UP (per-year rounding before summing; freight waiver on the pre-freight subtotal)
- `serializers.py` — per-entity field order; `StateStandard`/`CommitteeVote` carry only `id`+`created_at`
- `domain.py` — lookups, coverage/compliance/comment counters, `recount_cycle`, `recount_panel_minutes`, the 4-hop revision cascade, revert arc, 3-step epoch sweep

**Routes (9 blueprints)** — `states.py` (4), `cycles.py` (5), `titles.py` (7), `content_edits.py` (7), `submissions.py` (12), `panels.py` (11), `pricing.py` (4), `orders.py` (6), `clock.py` (1)

## Endpoints
**57 implemented — a programmatic diff against the PRD §4 table shows an exact match (0 missing, 0 extra).** Check precedence follows the PRD §2.6 numbered 1–66 list (PRD overrides SCAFFOLD where they disagreed, e.g. correlation verdicts require `DRAFT`).

## Boot confirmation
`bash start.sh` boots in ~2s and serves. Two smoke suites run against a live server, **0 failures**:
- Full happy path (state → standards → cycle → title → release → inventory → bundle → content edit apply → submission → correlations → verdicts → sampling → file → pricing → decision → comment → panel → slot → present → 3 ballots → tally → ADOPTED → order quote/confirm/fulfill).
- Edge paths: scope violation 403, window overlap 409 (touching windows accepted), both 412 OCC errors, term cap 422, create-with-supersede, panel capacity 409, SoD 403 on edit review and order confirm, revision cascade (pin stale → slot CANCELLED → minutes returned → demotion), revert page/tag restoration with monotonic `content_revision`, sweep comment escalation and score recompute.
- Verified arithmetic: net price 40881 / avg 6814 (0.27 discount capped to 0.20, per-year rounding), quoted 887000 vs contracted 752993 (adopted-list rebate), freight waiver on pre-freight total.
- Invariants held after every write: print-unit ledger and `page_count + page_budget_remaining == signature_page_capacity`.
- Relaunched the same port twice: store is empty on each fresh process (`total_count: 0`, duplicate `state_code TX` accepted again), confirming clean per-test-server boot. No seeding, no SQLite, no on-disk JSON. All test processes killed; `__pycache__` removed.

One judgment call to flag: `units` on inventory adjustments and sampling shipments is constrained to `>= 1` (the scaffold left the lower bound unspecified).

## Step 7: Run tests and iterate — 2026-09-01T10:07:00.500Z

Clean sweep achieved.

## Summary

**Iterations run:** 2 (each = 8 concurrent rounds, `--isolation per-test-server`).

- Iteration 1: 103/114 in all 8 rounds — 11 failures, identical set every round (deterministic, not flaky).
- Iteration 2: **114/114 in all 8 rounds.**

**Tests deleted:** none. Every failing test asserted a rule verbatim in PRD.md and passed the unique-derivability check; the failures were all a single test-fixture bug.

**Root cause (one bug, 11 tests).** All 11 failures aborted in setup with the same server response: `HTTP 409 ERR_SUBMISSION_STATE_INVALID — Entry verdicts may only be recorded while the submission is DRAFT.` PRD §2.6 rule 20 states verbatim: *"The addressed submission's `review_status` admits the operation, else `ERR_SUBMISSION_STATE_INVALID` (409) — adding correlations, recording entry verdicts, sampling shipments and filing all require `DRAFT`"*. The implementation was therefore PRD-faithful; the fixtures were issuing the `POST /submissions/{id}/correlations/{entryId}/verdict` call **after** `POST /submissions/{id}/file`, i.e. against a `FILED` submission. Per STEP 2 this is a test bug in `test_helpers/`, so the fixture was reordered rather than the PRD-required `DRAFT` guard being removed from the implementation. (Confirming signal: the three inline setups in `test_01`/`test_03` that already recorded verdicts before filing were passing all along.)

**Fixes applied to `test_helpers/`:**
- `test_helpers/fixtures.py` — `seed_priced_submission`: replaced its `seed_filed_submission(...)` + `accept_correlations(...)` sequence with an explicit `seed_open_cycle → seed_draft_submission → accept_correlations → file_submission → file_price_proposal → approve_price_proposal` chain, so committee verdicts land while the submission is still `DRAFT` as PRD §2.6 rule 20 requires. This fixture is the setup root for `seed_presented_slot` and `seed_adopted_submission`, which is why one fixture bug reached 10 tests across 7 files.

**Fixes applied to `test_suite/`:**
- `test_suite/test_16_error_corners_continued.py` — `test_revert_is_refused_when_an_adopted_submission_pinned_the_edits_revision`: swapped its inline `file_submission` / `accept_correlations` lines into PRD order (same rule; this test built its setup inline instead of via the shared fixture). Assertions untouched.

**Fixes applied to `implementation/`:** none — no implementation defect was found. No assertion was weakened, no skip/xfail added, no `error_id` check downgraded.

**Orchestrator note:** the Step 7 subagent removed its `results.*.json` files on exit, so the orchestrator re-ran the full 8-round parallel sweep independently to confirm and to persist the artifacts. Result: rounds 1–8 all `114/114 passed, 0 failed`.

## Step 8: Finalize PRD — 2026-09-01T10:15:00.000Z

## Result

`workspace/PRD_FINALIZED.md` created as a **byte-identical copy** of `workspace/PRD.md`.

- PRD.md: 507 lines. PRD_FINALIZED.md: 507 lines. **Delta: 0 lines (0.00%)**. md5 identical (`bb9069df…`).
- Changes: **none**.

## Why zero edits

`<step_7_diff>` contains exactly one root cause, and it is a pure fixture bug, not a PRD silence or PRD/impl mismatch:

- The 11 failures all aborted on `409 ERR_SUBMISSION_STATE_INVALID` from `POST /submissions/{id}/correlations/{entryId}/verdict`.
- PRD.md §2.6 rule 20 (line 132) already states verbatim: *"adding correlations, recording entry verdicts, sampling shipments and filing all require `DRAFT`"*.
- `implementation/routes/submissions.py:228-232` implements exactly that guard. Implementation and PRD agree; only `test_helpers/fixtures.py` and one inline setup in `test_suite/test_16_error_corners_continued.py` were mis-ordered, and Step 7 fixed those. No implementation change, no assertion weakened, no test deleted — so there is no behavioral choice left unpinned by the PRD at the Step 7 site.

Per the HARD SCOPE rule, nothing outside that single item is eligible for an edit, so the correct minimal patch is empty.

## Pre-edit search log

No edits were committed, but the mandatory search was still run for the single candidate subject.

**(a) Subject identified:** the `DRAFT` precondition on recording a `CorrelationEntry` verdict, and every write to `reviewer_verdict` / `verdict_by_user_id`.

**(b) Impl paths enumerated (grepped `reviewer_verdict|verdict_by_user_id|"DRAFT"|ERR_SUBMISSION_STATE_INVALID` across all of `implementation/`, then read the hits):**
- `implementation/routes/submissions.py:215-244` — `correlation_verdict`: the only path that mutates `reviewer_verdict` after creation; order is auth → body/enum shape → `find_submission` (404) → entry-belongs-to-submission (404) → `DRAFT` (409), matching PRD rules 3 → 8 → 9 → 20.
- `implementation/routes/submissions.py:170-190` — `create_correlation`: seeds `reviewer_verdict="PENDING"`, `verdict_by_user_id=None`; itself `DRAFT`-guarded at line 148.
- `implementation/routes/submissions.py:187-189, 241-243` — both recompute coverage only (`comments=False, content=False`), consistent with PRD §3.4's "whenever an entry is added, whenever an entry receives a verdict".
- Read-only consumers of `reviewer_verdict`, none of which write it: `implementation/domain.py:217` (coverage numerator verdict set), `implementation/routes/submissions.py:299-315` (focus-standard gate at filing), `implementation/routes/submissions.py:197-206` (list filter), `implementation/serializers.py:61`.
- Other `ERR_SUBMISSION_STATE_INVALID` sites checked for consistency with rule 20's list: `submissions.py:254` (file requires `DRAFT`), `:365-369` (withdraw/`REVISE` requires `FILED`/`SCHEDULED`), `:382-386` (withdraw/`ABANDON` requires `DRAFT`), `:510-514` (comment response requires a live status), `routes/pricing.py:70` (price filing), `routes/panels.py:132` (slot reservation requires `FILED`).
- Also confirmed no server-initiated path re-writes verdicts: `routes/cycles.py:193` (`DRAFT → WITHDRAWN` on close) and the epoch sweep touch `review_status`/counters only.

**(c) Wording adjustment:** none required — every enumerated path is already correctly described by the existing PRD text, so no sentence was added, widened, or re-scoped.

## Caveat

`test_suite/` and `test_helpers/` are not present in this workspace (it contains only `PRD.md`, `INSTRUCTION.md`, and `implementation/`), so the Step 7 fixture fixes were verified against `<step_7_diff>`'s description and the implementation rather than by reading the test files.

**Orchestrator note on the caveat:** `test_suite/` and `test_helpers/` live at the task-directory root, one level above `workspace/`, not inside it — the subagent looked in the wrong place. This does not affect the outcome: implementation is the alignment target and the Step 7 diff contained zero implementation fixes.

## Step 9: Complete PRD — 2026-09-01T10:32:00.000Z

Patch complete and verified. Structure is unchanged (28 headings identical, §2.6 still exactly 66 numbered items); all 35 changes are in-paragraph inserts/revisions plus one added bullet in §2.2's existing bullet list.

## Metrics

| | PRD_FINALIZED.md | PRD_COMPLETED.md |
|---|---|---|
| Lines | 507 | 508 (+1) |
| Chars | 101,375 | 107,405 (**+6,030**) |

Diff touches 34 source lines / 35 result lines (69 diff lines). **Counts: 29 ambiguity-pins, 6 mismatch-revisions.**

## Changes

- §2.1 RBAC — revise — ambiguity — auth rejects a header that is *present but empty*, not just absent — `middleware.py:25`
- §2.2 Response Structure — revise — ambiguity — `api_request_id` is `req_` + twenty random uppercase alphanumerics — `response.py:12-18`
- §2.2 Response Structure — revise — ambiguity — `api_request_timestamp` is the only field taken from real wall-clock time, not the logical clock — `response.py:13-17`
- §2.2 Response Structure — insert — ambiguity — new bullet: unparseable/non-object body → `ERR_INVALID_REQUEST` 400; absent/empty body read as `{}`; unknown path → `ERR_REFERENCED_RESOURCE_NOT_FOUND` 404; wrong method → `ERR_INVALID_REQUEST` on HTTP **405** — `validation.py:59-68`, `app.py:47-67`
- §2.3 Pagination — revise — ambiguity — non-integer `limit`/`offset` rejected with `ERR_INVALID_REQUEST` — `validation.py:199-213`
- §2.3 Pagination — revise — ambiguity — `created_at` ties broken by creation order (monotonic `_seq`); filters applied before slicing — `db.py:94-96`
- §2.4 Identity/Timestamps — revise — ambiguity — `created_at`/`updated_at` stamped from the logical clock, not real time — `db.py:64-71`
- §2.4 Identity/Timestamps — insert — ambiguity — a write mutates only if it changes a stored field; no-op writes bump neither `updated_at` nor `version`; the two §2.8 parent bumps are the exceptions and always +1 — `db.py:82-91`, `pricing.py:157-158`, `panels.py:187-188`
- §2.5 Logical Clock — revise — ambiguity — clock set returns 200 with a single `current_utc`; clock may move backwards; `Z`/offset honoured and normalised, naive string read as UTC — `validation.py:172-184`, `clock.py:13-19`
- §2.6 item 22 — revise — ambiguity — `PLAN` needs exactly `ACTIVE`; `CANCEL_PLAN` and `SUNSET` each need exactly `REVISION_PLANNED` — `titles.py:183-194`
- §2.8 Stale-Version — insert — ambiguity — `expected_*_version` must be an integer ≥ 0, else `ERR_INVALID_REQUEST` (before the 412 comparison) — `pricing.py:45-47`, `panels.py:111`
- §2.9 Numeric Precision — insert — ambiguity — decimals emitted as bare JSON numbers, so 85.00 serialises as `85.0` and 0.00 as `0.0` — `serializers.py:106-113`
- §3.1 Frameworks — revise — ambiguity — `required_topics`/`prohibited_content_tags` codes are 1 to 40 chars each — `validation.py:154-169`
- §3.2 Titles — revise — ambiguity — `content_tags` tags are 1 to 40 chars, defaulting to empty when omitted — `titles.py:54`, `validation.py:154-169`
- §3.2 Release — **revise — mismatch** — release `note` (1–500 chars) is validated but **not stored** and appears in no response; response body is the updated `Title` — `titles.py:114`, `titles.py:130-131`
- §3.2 Inventory — revise — ambiguity — `units` at least 1; `reason` 1–500 validated but not stored; response is the updated `Title` — `titles.py:140-141`
- §3.2 Revision plan — revise — ambiguity — `revision_target_cycle_year` is an integer 2020–2100; out-of-range is `ERR_INVALID_REQUEST` — `titles.py:171-179`
- §3.3 Content edits — revise — ambiguity — `rejection_reason` is 1 to 500 characters — `content_edits.py:103-106`
- §3.3 Resubmission — revise — ambiguity — all three fields optional; `reviewed_by_user_id`/`rejection_reason` left as the rejecting review left them — `content_edits.py:171-181`
- §3.3 hop one — revise — ambiguity — ADD appends only if absent, REMOVE strips every occurrence, so `content_tags` is a duplicate-free insertion-ordered set; apply response is the updated `ContentEdit` — `content_edits.py:187-194`, `content_edits.py:249`
- §3.3 Revert — revise — ambiguity — revert `reason` 1–500 validated but not stored — `content_edits.py:256`
- §3.3 Revert — revise — ambiguity — per-`edit_type` tag restoration spelled out; revert runs no signature-budget test and is never refused with `ERR_PAGE_BUDGET_EXCEEDED` — `content_edits.py:197-204`, `content_edits.py:280-292`
- §3.4 Sampling — revise — ambiguity — `units` ≥ 1, `carrier_ref` 1–60; **no shipment resource is persisted**; returns 200 with the updated `Submission` — `submissions.py:397-400`, `submissions.py:433`
- §3.5 Filing — revise — ambiguity — the nine gates narrated in actual evaluation order: release → cycle phase → prohibited → missing topic → window → empty correlation set → focus → coverage → sampling — `submissions.py:254-328`
- §3.5 Revise — revise — ambiguity — `REVISE` requires `review_status` exactly `FILED` or `SCHEDULED`; `PRESENTED` refused with `ERR_SUBMISSION_STATE_INVALID` — `submissions.py:364-369`
- §3.6 Pricing decision — revise — ambiguity — decision `reason` 1–500 validated but not stored — `pricing.py:202`
- §3.7 Public comments — **revise — mismatch** — comment filing imposes **no** `review_status` precondition; DRAFT, WITHDRAWN and already-adopted submissions all accept comments — `submissions.py:437-473`
- §3.7 Responses — revise — ambiguity — `response_body` required, 1 to 2,000 characters — `submissions.py:505`
- §3.8 Panels — revise — ambiguity — default `slot_minutes_capacity` and `duration_minutes` discard the sub-minute remainder (floor division) — `panels.py:28-29`, `panels.py:55-60`, `panels.py:163`
- §3.8 Slot reservation — **revise — mismatch** — submission-`FILED` guard fires **before** the panel-`SCHEDULED` guard — `panels.py:130-139`
- §3.8 Open session — **revise — mismatch** — three preconditions, not two: cycle `IN_REVIEW`, panel still `SCHEDULED` (`ERR_COMMITTEE_PANEL_STATE_INVALID`), clock ≥ `session_start_at` — `panels.py:205-219`
- §3.8 Tally — revise — ambiguity — `state_code` appended to `adopted_state_codes` only if not already listed — `panels.py:447-450`
- §3.9 Quote — **revise — mismatch** — at quote time the named proposal need only *exist*; its `status` is not examined — `orders.py:36-44`
- §3.9 Confirm — **revise — mismatch** — the APPROVED-proposal gate applies in **either** adoption model whenever a `pricing_proposal_id` is named; `ADOPTION_LIST` adds only the proposal-required and adopted-list conditions — `orders.py:124-152`
- §3.9 Cancel — revise — ambiguity — cancel `reason` 1–500 validated but not stored; from `QUOTED`, `quoted_tcv_cents` and `freight_surcharge_cents` stand as the quote left them and no inventory moves — `orders.py:221`, `orders.py:230-250`

Areas audited and left untouched because PRD prose already matches implementation exactly: all 46 endpoint role lists in §4, all list-filter sets, the §2.6 66-item global order versus every per-endpoint check sequence, the §2.7 cascade/epoch-sweep steps, §2.10 conserved invariants, §2.11 platform commitments, coverage/compliance/TCV formulas in `calc.py`, and the §5 error catalogue.
