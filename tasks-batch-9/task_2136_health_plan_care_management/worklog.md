# Worklog — task_2136_health_plan_care_management

## Step 1: Create task directory — 2026-08-22T00:00:00.000Z

Created `tasks/task_2136_health_plan_care_management/` and `tasks/task_2136_health_plan_care_management/workspace/`. Index 2136 derived from highest existing task index 2135.

## Step 3: Copy shared files — 2026-08-22T00:00:00.000Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2136_health_plan_care_management/workspace/INSTRUCTION.md` (1424 bytes). Executed ahead of Step 2 completion since it has no dependency on the scaffold.

## Step 2: Generate scaffold — 2026-08-22T00:00:00.000Z

All three scaffold artifacts are generated and lint-clean.

## What was produced

`/home/ubuntu/github/CodingPRD/tasks/task_2136_health_plan_care_management/`
- **`SCAFFOLD.yaml`** (§1.0–§1.7, 2754 lines) — no `scaffold_difficulty_design` / `scaffold_corner_design` keys
- **`SCAFFOLD_DIFFICULTY_DESIGN.yaml`** (§1.8, single top-level key, 23 instances across all 9 rules)
- **`SCAFFOLD_CORNER_DESIGN.yaml`** (§1.9, single top-level key, 59 instances across all 9 guide sections)

## Design summary

**Profile** — primary archetype `compliance_audit`, secondary `quota_allocation`; layers dual-variant calc, cascading side effects, rate/threshold triggers, OCC, selector policy; topology `graph` (flat FK-in-body creation + a self-referential `TransitionEvent.index_admission_event_id`); state-machine shape `parallel`; role model `segregation_of_duties`.

**Scale (biased above Expert per the "harder than expert" instruction)** — 14 entities, 51 endpoints, 55 error codes, 11 calculations, 9 state machines, 33 ordered validations, 5 roles, 2 OCC rules (both on `Enrollment.version`).

**Where the difficulty lives**
- Two dual-variant calcs on different domains: risk stratification (CONCURRENT 48/MODERATE vs PROSPECTIVE 76/RISING on identical events) and ROI (PRE_POST 305303¢ / 32.73 vs MATCHED_COHORT 284000¢ / 30.38).
- Combinatorial modes (a)/(b)/(c): nested min/max cadence clamps; pinned round-per-member-month and round-per-intervention order (9051¢ vs the wrong 9050¢); and a genuine circular dependency between engagement score and cadence tier resolved by `cadence_tier_snapshot` (67 vs the wrong 33).
- Depth-4 discharge→TOC→acuity→caseload→`OVER_CAPACITY`→empty auto-assign-pool cascade; depth-3 referral-unmet→social-need→goal-barrier→plan-posture cascade.
- Two overlap geometries on different resources: care-manager calendar (buffered-exclusive, back-to-back rejected, minimum gap exactly 15 min) vs community-resource slots (half-open, aggregate capacity, adjacency accepted).
- Two conserved quantities: caseload points across a transfer round trip, program staff minutes across intervention create/void.
- Three validation-priority conflict pairs across distinct category pairs (state/fiscal, safety/referential, temporal/constraint), each with a control call proving the masked rule.

**Verification performed**
- `scaffold_lint.py` verdict (pasted verbatim above): `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (955 calls scanned, 18 FKs all reverse-reachable).
- Custom checks: 94 unique instance names, 0 dangling `grounds` refs, 0 unbound `${var}` placeholders, all `excluded_because` targets resolve to real §1.8 instances, all 55 errors triggerable and referenced, every transition has preconditions + side effects, every endpoint role declared in §1.7, no forbidden concurrency vocabulary.
- Every formula-derived assert literal was computed in Python before being written (scores 48/76/85/84.5, ROI 170001/175101/305303/296252/32.73 and 168000/284000/274949/30.38, cost 3017×3=9051 vs 9050, engagement 67/100, caseload 4.0/8.0/10.5/12.5, all date arithmetic).

**One scaffold correction made mid-generation**: `ERR_NO_CARE_MANAGER_ASSIGNED` was removed (with its validation row and transition precondition) because `care_manager_id` is never null after a successful create, making the error untriggerable.

**Constraint honored**: no sibling `task_*/` directory was listed, read, or searched — everything derives from the scenario text plus the skill's own spec, reference guide, and lint script.

## Step 4: Generate PRD — 2026-08-22T00:00:00.000Z

PRD generated at `/home/ubuntu/github/CodingPRD/tasks/task_2136_health_plan_care_management/workspace/PRD.md` (434 lines), built incrementally across 8 append calls — no truncation.

**Document skeleton**
- §1 Introduction (3 paragraphs — angled at plan economics, the two opinionated mechanisms, and the logical clock)
- §2 with 10 subsections: Access Control · API Response Structure (verbatim) · Pagination · Resource Identity/Timestamps/Versions · The Logical Clock · Order of Validation (16-step normative ladder) · Precision, Rounding and Units · Optimistic Concurrency on Enrollment Writes · Caseload Ledger Discipline · Cascades and Hierarchical Consistency
- §3 with 9 subsections organised by domain lifecycle: Member Registry & Utilization Feed · Risk Stratification (two variants) · Programs/Care Managers/Enrollment Decision · Activation, Reassignment, End of Enrollment · Care Plan Authoring & Clinical Review · Outreach, Engagement & Cadence (the six-step completion order) · Transitions of Care · Social Needs & Closed-Loop Referrals · Outcome Measurement & Accreditation File
- §4 endpoint table (4 columns), §5 error table (2 columns). File ends at §5 — no audit footer.

**Verification counts (grep/script-verified against the scaffold)**
- Endpoints: **51/51** rows in §4
- Error codes: **55/55** rows in §5, and all **55 also referenced in §2/§3 narrative** (not just the table)
- Calculations: **11/11** expressed as precise prose (stratification both variants, caseload weight, auto-assignment selector, cadence tier, engagement score, next-touch projection, intervention cost, ROI both methods, care-manager slot conflict, resource slot capacity, accreditation file)
- State machines: **9/9** (Enrollment×2 parallel dimensions + TOC self-loop, CarePlan, CarePlanGoal, Intervention, Touch, SocialNeed, Referral) with every transition's from/to, preconditions→error_id, and side effects
- Validations: **33/33**, with the full priority ordering rendered as the §2.6 ladder plus each rule restated near the workflow it guards

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 134 required, 134 present, 0 missing
- endpoints[].request_body: 63 required, 63 present, 0 missing
- endpoints[].query_params: 23 required, 23 present, 0 missing
- computed response shapes (accreditation file + clock): 7 required, 7 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 33 checked, 33 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_enrollment_version + ERR_STALE_ENROLLMENT_VERSION/412 all named), 0 missing
- state_machines[].transitions: 9 machines / 38 transitions checked, 38 fully expressed, 0 missing
- calculations[]: 11 checked, 11 fully expressed, 0 missing
- validations[] conditions: 33 checked, 33 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 51 endpoints checked, all side-effect sets expressed, 0 missing
- entities[].fields[] structured content: 134 checked, defaults/initials/enums reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked (CONCURRENT/PROSPECTIVE, PRE_POST/MATCHED_COHORT, ACCEPT/DECLINE, 3 close-loop paths, APPROVE/REQUEST_REVISION, disenroll/graduate), 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 987
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: §2.2 diffs byte-identical to `section-2.2-response-structure.md` (only a trailing blank separator line added); a scan of §1–§3 for pseudocode operators (`>=`, `==`, `+=`, `IN {`, `round_half_up`, `min(`/`max(`/`floor(`) and fuzzy words (`approximately`, `roughly`, `conservatively`) returned zero hits. Neither `SCAFFOLD_DIFFICULTY_DESIGN.yaml` nor `SCAFFOLD_CORNER_DESIGN.yaml` was opened, grepped, or referenced.

**Orchestrator verification**: 434 lines; 51 endpoint rows in §4; 55 unique `ERR_*` codes present, matching the scaffold's 55 real codes (the only scaffold token absent from PRD is the spec's `ERR_XXX` placeholder, which is not a real error); file terminates cleanly at the end of the §5 error table.

## Step 6: Generate implementation — 2026-08-22T00:00:00.000Z

Implementation complete and verified.

## What was built

`workspace/implementation/` — Python 3 + Flask, 13 modules, no monolith:

| File | Role |
|---|---|
| `start.sh` | Guarded `pip install` (only when `flask` missing), `exec python3 app.py` |
| `requirements.txt` | `Flask==3.0.3` |
| `app.py` | Blueprint registration under `/care-management`, error handlers, per-request `RLock` (atomicity), `0.0.0.0:$PORT` (default 10000) |
| `core.py` | Logical clock (epoch `2026-08-01T00:00:00Z`), plain-dict store, UUID/seq, ISO-8601 (3 fractional digits) helpers, `ROUND_HALF_UP` helpers, all domain constants |
| `errors.py` | All 55 error IDs → HTTP status |
| `http_util.py` | `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more`, `X-User-ID`/`X-User-Role` auth, typed body validators |
| `serializers.py` | Per-entity output shapes (Decimal→float, datetime→ISO) |
| `domain.py` | Lookups, graph navigation, caseload ledger, cadence, posture, all cascades |
| `analytics.py` | Stratification, auto-assignment selector, ROI, accreditation file |
| `routes_member/program/enrollment/careplan/touch/social.py` | All 51 endpoints |

## Key fidelity decisions

- **§2.6 ladder is normative over §3 narrative ordering.** Where §3.5 lists "plan ACTIVE, then goal OPEN" for intervention creation, the ladder puts source state (9, `ERR_GOAL_NOT_OPEN`) before cross-entity gates (11, `ERR_CARE_PLAN_NOT_ACTIVE`) — implemented in ladder order. Same for touch scheduling and transfer (credential/licensure at 12, before same-manager at 14).
- **Request shape (3) precedes path resolution (5)** on every write endpoint.
- **Touch completion runs the six steps in pinned order**; TOC satisfaction fires inside step 2, so step 3's denominator reads the *restored* `cadence_tier_snapshot`. `reached_touch_count` is the monotone counter from step 2; the score's numerator is the separate windowed count.
- **§2.10 applied uniformly**: any record whose fields actually change gets `updated_at` + `version` bumped, including uncalled records (care manager ledger, program budget, goal counters, plan posture).
- **Two undeclared-error gaps** (no code exists in the catalogue): duplicate `external_member_id` and submitting a plan with zero goals → both `ERR_INVALID_REQUEST` (400).
- **`DISCHARGE` forces `episode_cost_cents` to 0** per "carries no episode cost of its own"; `discharge_disposition` required for `DISCHARGE`, nulled otherwise.
- **`DECLINED` + `SERVICE_DELIVERED`** is an undeclared transition → `ERR_REFERRAL_LOOP_NOT_CLOSABLE`.

## No seeded data

Storage is plain in-process dicts in `core.Store`; no `seed_*`, no SQLite, no file/JSON persistence, no `/tmp` cache. Verified on a fresh boot: `GET /members` returns `data: []`, `total_count: 0`, and the clock reads exactly `2026-08-01T00:00:00.000Z`.

## Boot check

`PORT=18967 bash start.sh` → `/health` returned **200** within 4 s, `ss` confirmed the listener on **`0.0.0.0:18967`**, `POST /care-management/programs` returned **201**, then the process was killed cleanly. Repeated fresh-process launches on six ports all came up and served correctly.

## Behavioural verification

Four scripted end-to-end suites (~140 assertions) run against fresh servers, covering: stratification maths under both variants (recency decay, chronic/SDOH capping, tier bands), auto-assignment ranking + `created_at` tie-break, caseload ledger conservation on transfer/graduation, OCC 412 on transfer and ROI, the DRAFT→PENDING_REVIEW→DRAFT revision loop, segregation of duties, staff-minute budget equality boundary, intervention cost rounding, the 15-minute buffered calendar geometry (back-to-back rejected, exactly-15-min gap accepted), community-resource half-open adjacency (accepted at capacity 1), consent/contract/domain gates, the barrier cascade and its reverse, TOC escalation + satisfaction with cadence restore, engagement disengagement → plan `SUSPENDED`/`DEFICIENT`, the four-hop disenroll cascade, graduation, `PRE_POST` and `MATCHED_COHORT` ROI arithmetic with pinned rounding order, the accreditation file, and pagination/auth/RBAC negatives. **All assertions pass** — the three residual `FAIL` lines in my scratch scripts were incorrect expectations on my part (3 whole months not 2; `ERR_SOCIAL_NEED_NOT_REFERABLE` correctly preempting `ERR_DUPLICATE_OPEN_REFERRAL` per the ladder; `has_more` false on a single-row store), each re-checked against the PRD and confirmed as correct server behaviour.

## Step 5: Generate unit tests — 2026-08-22T00:00:00.000Z

Generation complete. Summary:

## Output

**`test_helpers/`** (9 files) — `types.py` (28 enums + entity TypedDicts, with the three append-only ledgers correctly omitting `updated_at`/`version`), `api_client.py` (52 endpoint methods), `api_errors.py` (all 55 error IDs registered with the framework status map), `assertions.py` (per-entity assertions + caseload/ROI/compliance precision checkers), `factories.py`, `constants.py`, `test_users.py` (per-instance builders for all three `entity_backed` roles), `fixtures.py` (~600 lines: primitives + `setup_program_and_managers`, `setup_enrollment`, `setup_active_care_plan`, `setup_draft_care_plan`, `setup_discharge_escalated_enrollment`, `setup_referral_scenario`, `setup_completed_touch_history`), `__init__.py`.

**`test_suite/`** — `conftest.py` + 10 domain-named test files, **105 tests, all collecting cleanly**.

## Coverage audit (verified programmatically)

- Queue A: **23/23** difficulty instances, **46 tests**, >=2 each.
- Queue B: **59/59** non-stub corner instances, **59 tests**, >=1 each. All 11 `excluded_because:` stub pointers resolve to real difficulty instances; none translated.
- Every docstring carries exactly one `Design:` line resolving to a real instance; **199/199 quoted PRD fragments survive a whitespace-normalized literal match against PRD.md**; no `skip`/`skipif`/`xfail`; no scaffold references in generated code.

## Constant reconciliation — conflicts found

1. **`state_beats_fiscal_when_touch_targets_terminal_enrollment_on_full_manager` (Difficulty) — index asserts a wrong error code.** The index books a touch on a `DISENROLLED` enrollment carrying no care plan and expects `ERR_ENROLLMENT_NOT_ACTIVE`. PRD §3.6 enumerates exactly five booking gates and enrollment status is not among them; PRD §2.6 rung 11 maps touch scheduling's cross-entity gate failure to `ERR_CARE_PLAN_NOT_ACTIVE` ("`ERR_ENROLLMENT_NOT_ACTIVE` where the missing element is the active enrollment" applies only to plan submit/review). The index-only outcome fails unique derivability. **Reconstructed PRD-safely**: manager Y is pushed to 14.5/12.0 via a HIGH activation (PRD §3.4 states activation runs no capacity precheck), then the dual-failure booking targets an **ACTIVE** enrollment whose only plan is still `DRAFT` — so `ERR_CARE_PLAN_NOT_ACTIVE` (rung 11) is uniquely derivable and still demonstrably pre-empts `ERR_CARE_MANAGER_OVER_CAPACITY` (rung 16), proven by the control call. The instance's claim is preserved, its wrong literal is not.

2. **`care_manager_create_rejects_computed_caseload_field` (Corner/entities) — partially skipped.** Index asserts that supplying the computed `assigned_caseload_points` returns `ERR_INVALID_REQUEST`. PRD never states that unknown/computed input fields are rejected, and §2.4 says a client-supplied `id` is *ignored* — so both "reject" and "ignore" are PRD-faithful. Only the clean-create half survives (`assigned_caseload_points` 0.0 / `capacity_status` OPEN / `active_enrollment_count` 0, verbatim in §3.3).

3. **`member_system_fields_are_server_minted_untyped_uuids` (Corner/entities) — literal instant dropped.** Index asserts `created_at == 2026-08-01T00:00:00.000Z`. PRD §2.5 binds the logical clock to "every deadline, window, age, and cadence rule" and §2.4 binds `updated_at` to mutations, but never says `created_at` reads the logical clock. The test keeps the bare-UUID form, the ISO-8601 shape and `version == 1`.

4. **Numeric literals all reconciled and confirmed against PRD prose** — 48/76 variant divergence, 84.5→85, 66.5 utilization, 3017/9051 vs 9050, 72000/216000/206949/22.86, 170001/175101/525303/305303/296252/32.73, 168000/504000/284000/274949/30.38, engagement 67/33/100, cadence clamps 2026-09-09 / 2026-09-02 / 2026-08-18 / 2026-09-13 / 2026-09-01, caseload 4.0/2.0/1.0/6.0/10.5/12.5/8.0, TOC due 2026-08-03, review due 2026-10-30. No further discrepancies.

Also softened: assertions of the form `x["nullable_field"] is None` now use `.get(...)` so an implementer who omits null keys from the serializer is not failed on serializer style where the PRD does not pin field presence.


## Step 7: Test and iterate to green — 2026-08-22T00:00:00.000Z

All 8 parallel rounds green. Exiting.

## Summary

**Iterations run:** 2 (each an 8-round parallel stability sweep, 104–105 tests per round under `per-test-server` isolation).

- **Sweep 1** (105 tests): 104/105 in all 8 rounds — one *deterministic*, non-flaky failure, identical in every round.
- **Sweep 2** (104 tests): **104/104 in all 8 rounds.**

**Tests deleted (1):**

- `test_second_open_referral_on_the_same_need_is_rejected` (`test_suite/test_08_social_needs_and_referrals.py`) — **ERROR PRECEDENCE SILENCE / unreachable-by-construction**. Scaffold rule that drove generation: `Corner/validations/second_open_referral_for_same_need_returns_duplicate_open_referral`.

  The test asserted `ERR_DUPLICATE_OPEN_REFERRAL` (§2.6 rung 15) but got `ERR_SOCIAL_NEED_NOT_REFERABLE` (rung 9). This is exactly the ladder-masking hazard, so I checked STEP 2 first — whether the fixture could be repaired to satisfy every earlier rung. **It cannot**: PRD §3.8 says a persisted referral "moves the social need to `REFERRED`", and a need leaves `REFERRED` only via a closure, which simultaneously removes that referral from `SENT`/`ACCEPTED`. The invariant *"a need is referable <=> it carries no open referral"* therefore holds on every PRD-declared path, making rung 15's duplicate check unreachable. I confirmed this empirically against a live server across all four candidate paths (2nd send while `SENT`, while `ACCEPTED`, after `CLOSED_UNMET`->`UNMET_ESCALATED`, and after a `DECLINED` referral) — every one returned `ERR_SOCIAL_NEED_NOT_REFERABLE` or succeeded legitimately.

  Relaxation to `validate_error_is_one_of([...])` was **not** permitted here: §2.6 states "The ordering is normative: a request that violates two rules always surfaces the earlier one", and §3.8's own gate list gives the same relative order (referable before duplicate). Both readings uniquely determine `ERR_SOCIAL_NEED_NOT_REFERABLE`, so the PRD does not support the "`ERR_DUPLICATE_OPEN_REFERRAL` is possible" reading at all.

**Fixes applied to `test_helpers/`:** none. Audited `fixtures.py`, `test_users.py`, `constants.py` and `conftest.py` against PRD §2.1's role-to-resource ownership model and §3's payload shapes — the identity-backed role builders (`make_care_manager_headers`, `make_clinical_reviewer_headers`, `make_community_partner_headers`) and the composite scenario builders were all faithful.

**Fixes applied to `workspace/implementation/`:** none. The implementation was already correct on the one failure — `routes_social.py:create_referral` orders the gates exactly per §2.6 (rung 9 source-state, then 12 consent, 13 temporal, 14 referential, 15 uniqueness/capacity). Per the cardinal rules I left the PRD-required `ERR_DUPLICATE_OPEN_REFERRAL` check in place at rung 15 even though it is dead code under the spec, rather than reordering the ladder to satisfy the test.

**Also verified:** storage is in-memory dicts only — no SQLite, no JSON dump, no `/tmp` cache, no seeding or preloading — so `start.sh` re-invocation wipes all state between tests.

**Orchestrator verification**: all 8 `results.{1..8}.json` confirm `passed == total == 104`, `failed == 0`; `test_suite/` now holds 104 test functions.

## Step 8: Finalize PRD — 2026-08-22T00:00:00.000Z

**No patch needed.** `workspace/PRD_FINALIZED.md` is a byte-identical copy of `PRD.md` (434 lines, 88196 bytes, md5 `5accd0f8b84a9a593a1e412a48e7eb0b`).

## Line counts
- PRD.md: 434 lines
- PRD_FINALIZED.md: 434 lines
- Delta: 0 lines (0.0%)

## Changes
None.

## Why the single Step 7 item does not yield a PRD edit

The one Step 7 item is a test deletion with zero implementation fixes and zero `test_helpers/` fixes: `test_second_open_referral_on_the_same_need_is_rejected`.

I verified Step 7's reasoning against the implementation rather than trusting it:

- `workspace/implementation/routes_social.py:122` raises `ERR_SOCIAL_NEED_NOT_REFERABLE` (§2.6 rung 9) before the duplicate check at `routes_social.py:146-149` (§2.6 rung 15).
- PRD §2.6 declares its ladder normative ("a request that violates two rules always surfaces the earlier one") and places rung 9 before rung 15; §3.8's own gate narrative gives the same relative order for this pair (referable, then duplicate). So the PRD **uniquely determines** `ERR_SOCIAL_NEED_NOT_REFERABLE` for the deleted test's scenario — impl matches PRD, and there is nothing left open to pin.
- I confirmed the unreachability claim independently by enumerating every social-need status write in the implementation: `routes_social.py:35` (`IDENTIFIED` on creation), `routes_social.py:183` (`REFERRED` on referral persist), `domain.py:377` (`UNMET_ESCALATED`), `domain.py:399` (`RESOLVED`). The only two writers of a referable status (`domain.py:377`, `:399`) are both reached solely from `close_referral_loop` (`routes_social.py:277-282`), which simultaneously moves the referral to `CLOSED_MET`/`CLOSED_UNMET` — so a referable need never carries a `SENT`/`ACCEPTED` referral. A `DECLINED` referral leaves the need in `REFERRED` (`routes_social.py:233` writes no need status), which is also non-referable. The invariant holds on every impl path, matching what the PRD describes.

Since the PRD already pins this behavior and the implementation already conforms, an edit here would be manufactured — and, per the NO-NEW-MISMATCH rule, any rewording of §2.6/§3.8's ordering (for instance to describe `ERR_DUPLICATE_OPEN_REFERRAL` as dead) would risk contradicting the check that the implementation still executes at `routes_social.py:146-149`.

## Per-edit pre-edit search log
No edits were committed, so there is no per-edit log. The one candidate edit I evaluated and rejected:

- (a) **Subject considered:** referral-creation gate ordering, specifically the reachability/precedence of `ERR_DUPLICATE_OPEN_REFERRAL` vs `ERR_SOCIAL_NEED_NOT_REFERABLE`.
- (b) **Impl paths enumerated and read/grepped:** `routes_social.py:109-185` (`create_referral`, full gate ladder), `routes_social.py:210-239` (`decide_referral`), `routes_social.py:242-288` (`close_referral_loop`), `routes_social.py:35` (need creation), `domain.py:377-420` (`escalate_social_need` / `resolve_social_need`), `core.py:230` (`SOCIAL_NEED_STATUSES`), `analytics.py:27` (open-need aggregation); grepped every `["status"] =` write across `routes_social.py`, `domain.py`, `core.py`, `analytics.py`.
- (c) **Wording adjustment:** edit dropped entirely — all enumerated paths are already correctly described by the existing §2.6 and §3.8 prose.

One incidental observation, deliberately **not** patched because it does not trace to any `<step_7_diff>` item (HARD SCOPE): `routes_social.py:255-257` makes a `DECLINED` referral closable only with `resolution == "SERVICE_NOT_DELIVERED"`, rejecting `DECLINED` + `SERVICE_DELIVERED` with `ERR_REFERRAL_LOOP_NOT_CLOSABLE`. PRD §3.8 enumerates exactly three closure paths but phrases the gate as status-based ("A referral in any other status cannot be closed at all"). Flagging it for whoever owns a later pass; it was not exercised by Step 7.

**Orchestrator note**: the Step 7 worklog entry was initially misfiled into `workspace/implementation/worklog.md` by a persisted shell `cd`; it has been relocated into this file and the stray copy deleted. All subsequent worklog writes use absolute paths.

## Step 9: Complete PRD — 2026-08-22T00:00:00.000Z

Done. `workspace/PRD_COMPLETED.md` is written.

## Summary

**Source vs output:** `PRD_FINALIZED.md` 434 lines / 88,196 chars → `PRD_COMPLETED.md` 434 lines / 93,858 chars (**+5,662 chars**, 27 lines revised in place, zero new lines/paragraphs/sections). Section-header and table-row counts unchanged.

**Counts:** 29 total changes — **19 ambiguity-pins**, **10 mismatch-revisions**.

### Changes

- §2.2 — insert — ambiguity — `api_request_timestamp` comes from real wall-clock time, not the §2.5 logical clock — `http_util.py:15-19`, `core.py:93`
- §2.3 — insert — ambiguity — same-`created_at` ties break by creation order; descending listings reverse that same total order — `domain.py:34-43`
- §2.6 r11 — revise — mismatch — the enrollment-`ACTIVE` review gate binds only the `APPROVE` branch; `REQUEST_REVISION` has no such gate — `routes_careplan.py:117-137`
- §2.9 — insert — ambiguity — a ledger recompute that moves none of the three figures leaves `updated_at`/`version` untouched; `active_enrollment_count` is a full recount — `domain.py:196-219`
- §3.1 — insert — ambiguity — duplicate `external_member_id` → `ERR_INVALID_REQUEST`, after all field-shape checks — `routes_member.py:31-34`
- §3.1 — revise — ambiguity — a discharge discards any supplied `episode_cost_cents` (stores 0); a disposition on a non-discharge is enum-validated then discarded; missing disposition on a discharge is `ERR_INVALID_REQUEST` — `routes_member.py:124-138`
- §3.1 — insert — ambiguity — `index_admission_event_id` is resolved (`ERR_TRANSITION_EVENT_NOT_FOUND`) even on non-discharges, then discarded — `routes_member.py:130-136`
- §3.2 — insert — ambiguity — refreshing the member's cached tier increments the member's `version` — `analytics.py:118-123`
- §3.3 — insert — mismatch — enrollment gates fire credential/licensure (r12) → duplicate/stratification/tier (r14) → caseload (r16), not in narrative order — `routes_enrollment.py:36-62`
- §3.3 — revise — mismatch — the "three further gates" split: two before the r14 gates, the caseload ceiling after — `routes_enrollment.py:36-62`
- §3.3 — insert — ambiguity — the three money/budget program fields are required integers >= 0; the three interval fields are optional integers — `routes_program.py:226-231`
- §3.4 — revise — mismatch — transfer checks credential/licensure (r12) **before** the same-manager test (r14) — `routes_enrollment.py:163-170`
- §3.4 — insert — ambiguity — activation reuses the full §3.6 step-6 three-adjustment projection — `routes_enrollment.py:138`, `domain.py:240-254`
- §3.4 — insert — ambiguity — ending a `GRADUATED`/`DISENROLLED` enrollment → `ERR_ENROLLMENT_ALREADY_TERMINAL`, before the reason is read — `routes_enrollment.py:193-194`
- §3.4 — insert — ambiguity — an `AT_RISK` goal closing clears `barrier_flag` and drops `at_risk_goal_count`; the `CLOSED` plan's posture is recomputed (never `DEFICIENT`) — `domain.py:296-327`
- §3.5 — revise — mismatch — intervention creation fires `ERR_GOAL_NOT_OPEN` (r9) **before** `ERR_CARE_PLAN_NOT_ACTIVE` (r11) — `routes_careplan.py:206-212`
- §3.5 — insert — ambiguity — `void_reason` is free text, required non-empty (`ERR_INVALID_REQUEST`); a void has **no** plan-`ACTIVE` gate — `routes_careplan.py:281-300`
- §3.5 — insert — ambiguity — a goal-less submit → `ERR_INVALID_REQUEST`, after the `DRAFT` check and before the enrollment check — `routes_careplan.py:83-89`
- §3.5 — revise — mismatch — review fires `ERR_SEGREGATION_OF_DUTIES` (r8) **before** `ERR_CARE_PLAN_NOT_IN_REVIEW` (r9) — `routes_careplan.py:110-114`
- §3.5 — insert — mismatch — a missing/blank `revision_note` is a rung-3 `ERR_INVALID_REQUEST` raised before the plan is resolved; the revision branch has no enrollment gate — `routes_careplan.py:102-106`
- §3.6 — insert — ambiguity — `cancel_reason` required non-empty → `ERR_INVALID_REQUEST` — `routes_touch.py:114`
- §3.6 — insert — mismatch — `ERR_DOCUMENTATION_REQUIRED` (r12) precedes `ERR_TOUCH_NOT_YET_DUE` (r13); a `NOT_REACHED` note is stored verbatim — `routes_touch.py:159-165`
- §3.8 — insert — ambiguity — a social need may be recorded against any enrollment, no lifecycle or ownership gate — `routes_social.py:241-248`
- §3.8 — revise — mismatch — `ERR_SOCIAL_NEED_NOT_REFERABLE` (r9) fires **first**, ahead of consent/window/referential gates — `routes_social.py:341-343`
- §3.8 — insert — mismatch — a missing/blank `decline_reason` is a rung-3 `ERR_INVALID_REQUEST` raised before the referral is resolved — `routes_social.py:435-438`
- §3.8 — insert — ambiguity — `outcome_note` missing/blank → `ERR_INVALID_REQUEST` at rung 3 — `routes_social.py:467`
- §3.8 — revise — mismatch — closure ownership binds only a `CommunityPartner` caller; **any** `CareManager` may close, sender or not — `routes_social.py:470-472`
- §3.8 — revise — **the flagged item** — ambiguity — the closability gate reads `resolution` as well as status: `ACCEPTED` under either resolution, `DECLINED` under `SERVICE_NOT_DELIVERED` only; `DECLINED` + `SERVICE_DELIVERED` → `ERR_REFERRAL_LOOP_NOT_CLOSABLE` — `routes_social.py:473-478`
- §3.9 — insert — ambiguity — a never-activated enrollment (`activated_at` null) also yields `ERR_MEASUREMENT_PERIOD_EMPTY`; no `enrollment_status` gate on measurement — `analytics.py:176-181`, `routes_enrollment.py:218-220`
- §3.9 — insert — ambiguity — `deficiency_counts` always carries all six keys (0 where unexhibited), each enrollment counting at most 1 per code; `deficient_enrollment_ids` follows the same ascending `created_at` order — `analytics.py:252-285`

**Not changed** (verified impl already uniquely pinned by PRD prose): stratification windows/weighting/capping, auto-assignment filter-rank-tiebreak, caseload arithmetic, calendar buffer geometry, engagement steps 1–6, TOC cascade and satisfaction, resource-concurrency probing, ROI month qualification and rounding order, accreditation deficiency semantics, and the full §5 status-code table.

**Orchestrator verification**: `PRD_COMPLETED.md` holds 434 lines / 93,858 chars (+5,662 over source), with 27 markdown headers, 55 §5 error rows and 51 §4 endpoint rows — all identical to `PRD.md`, confirming in-place revision with no new/dropped sections and no truncation.
