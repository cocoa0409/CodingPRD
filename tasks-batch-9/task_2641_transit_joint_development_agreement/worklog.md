# Worklog — task_2641_transit_joint_development_agreement

## Step 1: Create task directory — 2026-09-03T23:44:00.000Z

Created `/home/ubuntu/github/CodingPRD/tasks/task_2641_transit_joint_development_agreement` and `.../workspace` (pre-assigned path; no index auto-allocation performed).

## Step 2: Generate scaffold artifacts — 2026-09-04

Wrote the three §1.0–§1.9 artifacts from the scenario description plus the scaffold-generator
specification only (no sibling task inspected):

- `SCAFFOLD.yaml` — §1.0–§1.7: 13 entities, 11 state machines, 2 concurrency rules, 9 calculations,
  45 validations (+3 declared priority conflicts), 59 endpoints, 55 errors, 7 roles.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8: 9 rule blocks x 2 differentiated instances = 18.
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9: 9 sections, 89 instances (60 executable test recipes,
  29 `excluded_because` stubs citing the §1.8 instance that already asserts the corner).

Post-write fixes: converted every §1.5 `input:` from an inline-dict string to the canonical list form
(`input: [field, "opt?"]`, original types kept as a trailing comment) so `scaffold_lint.py` can read
them; added the missing `GET /jda/sites` inventory list endpoint; clarified the
ISSUED -> CANCELLED award cascade so a direct negotiation period never cancels its own proposal's
solicitation; conditioned the StagingWindow approval facility-replacement guard on
`AgencySite.transit_facility_present`.

`scaffold_lint.py`: VERDICT clean lint (59 endpoints, 13 entities, 18 §1.8 instances,
60 §1.9 instances, 1065 calls scanned). All 55 §1.6 errors have at least one executable trigger,
all 59 endpoints are exercised by at least one structured call, and no `${var}` is unbound.

## Step 3: Copy shared files — 2026-09-04T01:19:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `workspace/INSTRUCTION.md`. Verified all three
scaffold artifacts present (SCAFFOLD.yaml 2909 lines, SCAFFOLD_DIFFICULTY_DESIGN.yaml 1685 lines,
SCAFFOLD_CORNER_DESIGN.yaml 4816 lines) and that Step 2 did not disturb `workspace/`.

## Step 4: Generate PRD — 2026-09-04T01:35:00.000Z

`workspace/PRD.md` — 445 lines / 94,190 bytes. Truncation guard: verified the file ends at a real
section boundary (the complete `## 5. Error Code Catalogue` table, final row `ERR_BELOW_PERMISSIBLE_FLOOR`),
not mid-sentence. Neither design index was read.

Subagent summary (verbatim):

Sections: 1. Introduction; 2. Global Specifications (2.1 Operators/Roles/Duty Boundary, 2.2 API Response
Structure, 2.3 Pagination and List Ordering, 2.4 Record Identity/Timestamps/Immutable Event Records,
2.5 The Logical Clock, 2.6 Money/Rounding/Pinned Evaluation Order, 2.7 The Federal Interest Ledger,
2.8 Parallel State Dimensions and Cascade Discipline, 2.9 Nested Path Resolution, 2.10 Stale-Read
Protection on Sites and Shared Facilities, 2.11 Validation Precedence); 3. Business Logic & Workflows
(3.1 inventory + developability, 3.2 appraisal / federal interest basis / permissible transfer floor,
3.3 developer registration + solicitation + proposals, 3.4 closing/ranking/award cascade, 3.5 exclusive
dealing periods, 3.6 agreement drafting + agency revenue, 3.7 agency review/board/execution, 3.8 federal
disposition approval + reversal cascade, 3.9 facility replacement / shared facilities / staging /
maintenance); 4. Endpoint Definitions; 5. Error Code Catalogue.

Coverage: 13/13 entities, 59/59 endpoints, 55/55 errors, 9/9 calculations, 45/45 validations,
11/11 state machines (incl. both parallel dimensions of JointDevelopmentAgreement), 7/7 roles,
2/2 concurrency rules.

Hard Contract reports: (1) Field-Name Coverage PASS — 111/111 entity field names and 93/93 endpoint
input identifiers present as inline code, 0 missing. (2) Rule Coverage PASS — all 45 validations,
11 state machines, 9 calculations with pinned evaluation orders, both OCC rules (write endpoint,
occ_field, 412 + error_id), all cascade branches and field defaults. Three gaps repaired in the manual
walk: §2.10 now names `POST /jda/sites/{id}/valuations` and `POST /jda/staging-windows`; §3.9 states the
peak-occupancy bay-capacity test runs at request time as well as decision time (term-envelope refusal
takes precedence); `certified_at` is stated null-on-creation for both ReadinessAssessment and
ValuationDetermination. (3) §3 Path Purity PASS — 835 backtick tokens in §3, 0 paths / 0 bare methods /
0 method+path combinations.

Note for the pipeline: a naive backtick-span extraction regex gives a false Contract-1 failure here
because the fenced JSON blocks in §2.2 flip backtick parity; strip fenced blocks before verifying.

## Step 6: Generate implementation — 2026-09-04T02:03:00.000Z

(Steps 5 and 6 were launched concurrently in a single assistant message, so the impl generator had
physical isolation from `test_suite/` — the directory did not exist when it started. Step 6 finished
first; Step 5's entry follows below.)

Subagent summary (verbatim):

Implementation complete and smoke-verified. 2,696 lines of Python in
`workspace/implementation/`: app.py (76) Flask app + ApiError/404/405/415/400/Exception handlers +
8 blueprints + host 0.0.0.0 port $PORT, no seeding; store.py (176) 13 empty in-memory dicts, logical
clock default 2026-08-01T00:00:00Z, hidden `_seq`, ISO-8601 3-fraction formatter; errors.py (79)
55-entry error->status map; envelope.py (43) meta/object/array/error/pagination envelopes;
authz.py (36) 7 roles via X-User-ID/X-User-Role, ERR_UNAUTHENTICATED / ERR_FORBIDDEN_ROLE;
shape.py (190) body/query coercion -> ERR_INVALID_REQUEST, paging() limit 1..100; enums.py (29);
calc.py (257) the 9 calculations + staging peak occupancy, Decimal/ROUND_HALF_UP only;
common.py (220) public(), pagination, child lookups, overlap predicates, derived counts, cascade
helpers; routes_reads.py (288) 25 GETs; routes_sites.py (240); routes_solicitation.py (231);
routes_negotiation.py (149); routes_agreement.py (262); routes_federal.py (148); routes_ops.py (272).
Plus requirements.txt (flask>=2.0) and start.sh (executable, foreground `exec python3 app.py`,
guarded pip install, reads $PORT, binds 0.0.0.0).

Endpoint coverage: app.url_map enumerates exactly 59 endpoints (25 GET + 33 POST + 1 PATCH,
including POST /_clock/set_current_utc) — one-for-one with the declared surface.

The 9 calculations (calc.py, Decimal + ROUND_HALF_UP, integer cents, three pinned orders honored):
1 readiness PRELIMINARY = unweighted mean of four sub-scores, tier null. 2 readiness CERTIFIED =
weights .35/.25/.25/.15 minus min(12, 3xencumbrance_count) minus 0.10xfederal_interest_pct, rounded
exactly once at the end, floored at 0.00, tiered at 70/50. 3 permissible transfer floor = TSU rate
bands 75/50/25 -> .30/.20/.10, +.05 affordable bonus, cap .30; FMV_STRICT floor = appraised value,
else max(appraised - credit, federal_floor). 4 evaluation score = each component quantized to 2dp
before its cap (value 40 / affordable 25 / ridership 20 / design), then 10-point unprequalified
penalty, floored at 0. 5 ranking = -evaluation_score, -affordable_pct, created_at, _seq (id never
participates; hidden _seq is the real tie-break since many records share one logical instant).
6 annual revenue to agency = credit tier keyed on the pre-credit subtotal (1M/2.5M/5M ->
.04/.08/.12), +.03 affordable bonus, ceiling .15. 7 consideration value = GROUND_LEASE annual
revenue x 20; FEE_DISPOSITION purchase price. 8 maintenance allocation = per-line rhu(cost x share)
then summed, agency absorbs the residue (PRD worked example reproduces exactly: 43,314 / 123,750 /
80,436). 9 federal interest amount = rhu(basis x site_area_share_pct / 100). Plus the staging
peak-occupancy rule (half-open intervals, boundary set = candidate start union conflicting starts,
APPROVED windows only, adjacency never conflicts).

The 2 OCC rules, both at scaffold priority 7 (after FK existence 5 and Developer ownership 6, before
every state gate): POST /jda/sites/{id}/valuations -> expected_site_version != site.version ->
ERR_STALE_SITE_VERSION 412; POST /jda/staging-windows -> expected_facility_version !=
facility.version -> ERR_STALE_FACILITY_VERSION 412, and a successful request bumps the facility
version so the next requester must re-read available_bay_capacity.

Smoke test: two scenarios, both green, servers stopped by recorded PID (no broad pkill). Scenario 1
(34 assertions) covered 401/404/empty list, site create + duplicate-code 409, assessment draft 88.75
-> certify 82.45 READY, release, stale-OCC 412, valuation (credit 3,000,000 / federal floor
4,000,000 / permissible floor 7,000,000), certify, developer, solicitation issue, proposal score
90.5, close -> rank 1, award -> site UNDER_AGREEMENT, agreement (credit 77,000 / annual 1,023,000 /
consideration 20,460,000), submit-for-review, board-approve, disposition filing with ledger
encumbrance (basis = encumbered + unencumbered), facility replacement legal/illegal transitions,
facility register, staging OCC 412 + outside-envelope 422 + request/approve (available 6->4) + close
(->6), empty line items 422, maintenance charge (43,314/80,436, no version/updated_at on the event
record), determination APPROVED, execute (period -> CONVERTED), clock set, pagination meta and
limit=0 -> 422. Scenario 2 (40+ assertions) covered the reversal cascade: deficit 2 -> COMPLETE lands
on DEFICIENT -> execute blocked 409 -> cured to COMPLETE; capacity refused at request time; adjacency
accepted; reject-without-reason 422; rejected window leaves facility capacity and version untouched;
a REJECTED determination produced FTA_REJECTED + REVISION_REQUESTED, revision_notes == "federal
disposition rejected: no independent utility", board_resolution_number null, valuation SUPERSEDED,
window SUSPENDED with capacity_released true, facility capacity restored to 5, site ledger fully
released; closing the suspended window a second time returned nothing and did not bump the facility
version; re-close 409, re-determine 409; PATCH reset to DRAFTING/NOT_SUBMITTED with
submitted_by_user_id cleared; advancing the clock expired the period, rejected the held proposal and
released the site to SOLICITATION_READY.

Storage is process-local dicts only, nothing seeded at startup, no file read or written at runtime
(the smoke-run __pycache__ was removed).

## Step 5: Generate unit tests — 2026-09-04T03:11:00.000Z

Verified `test_helpers/` and `test_suite/` landed at the TASK ROOT (nothing stray under `workspace/`);
removed the generators' `__pycache__` dirs.

Subagent summary (verbatim):

Generation complete. Both queues are fully translated.

Files written (task root, not under workspace/): `test_helpers/` — 2,198 lines total: __init__.py 57,
api_client.py 328, api_errors.py 136, assertions.py 353, constants.py 85, factories.py 289,
fixtures.py 540, test_users.py 86, types.py 324. `test_suite/` — 6,052 lines total: conftest.py 55;
test_01_readiness_and_valuation_variants.py 304, test_02_agreement_money_and_allocation.py 272,
test_03_agreement_dimensions_and_site_cycle.py 304, test_04_award_and_federal_rejection_cascades.py
349, test_05_validation_precedence_pairs.py 187, test_06_boundary_precision.py 183,
test_07_cross_entity_gates.py 192, test_08_temporal_overlap.py 210, test_09_compensating_invariants.py
220 (queue A); test_10_entities.py 482, test_11_state_machines.py 322, test_12_calculations.py 328,
test_13_validations.py 526, test_14_endpoints.py 422, test_15_errors.py 814, test_16_rbac.py 474,
test_17_cross_cutting_layers.py 300, test_18_consistency_model.py 108 (queue B).

Coverage: total test functions 111 (pytest collects exactly 111; every one carries exactly one
`Design:` line as the last docstring line — zero untagged, zero dual-tagged, zero bogus tags, zero
tags pointing at excluded_because stubs). Queue A (Difficulty) 18/18 instances -> 52 tests. Queue B
(Corner) 59/60 executable instances -> 59 tests; per section entities 12/12, state_machines 7/7,
calculations 6/7, validations 9/9, endpoints 5/5, errors 11/11, rbac 5/5, cross_cutting_layers 3/3,
consistency_model 1/1. The 29 excluded_because stubs were not translated.

Skipped instances (1): Corner/calculations/corner_federal_interest_basis_ignores_draft_valuations —
non-unique derivability. The instance asserts a DRAFT valuation leaves the site's federal interest
basis untouched, but PRD §3.2 states that recording a determination (which lands in DRAFT) refreshes
federal_interest_basis_cents and bumps the site version. The PRD therefore derives the opposite
outcome; gap left as a gap, no placeholder or xfail.

Adjudications where the design conflicted with the PRD:
1. Corner/errors/corner_award_before_close_then_shortlist_after_award_rejected — design expects
   ERR_PROPOSAL_NOT_ELIGIBLE from shortlisting a SELECTED proposal on an AWARDED solicitation, but
   §2.11 category 9 orders solicitation state ahead of proposal state and §3.3 requires the
   solicitation to be ISSUED/CLOSED, so the PRD derives ERR_SOLICITATION_NOT_ISSUED. Dropped that one
   trigger/assert; kept the ERR_SOLICITATION_NOT_CLOSED refusal and the post-close award cascade.
2. Corner/rbac/corner_other_roles_exclusive_operations_and_missing_headers_rejected — dropped the
   design's fifth (201) trigger because its body carries a non-existent transfer_basis enum value.
   Kept the four refusals (401 unauthenticated, 403 wrong role on valuation create, 403 VO certifying
   an assessment, 403 VO moving the clock), legitimate because §2.1/§2.11 run auth and role before shape.
3. Corner/rbac/corner_developer_cannot_act_on_another_developers_resources — design asserts the
   owner's own proposal reads SELECTED, but its setup uses a direct negotiation grant and §3.5 shows a
   direct grant only moves the site and cancels *other* solicitations; it never selects the proposal.
   Asserted the derivable SUBMITTED instead.
4. Corner/cross_cutting_layers/corner_extension_ceiling_is_cumulative_not_windowed — same direct-grant
   issue for its final Proposal.status == SELECTED assertion. Instead of dropping the assert, the
   period is created through the §3.4 award path (which does derive SELECTED, ACTIVE, extension_count
   0 and UNDER_AGREEMENT), leaving the instance's actual claim — the cumulative extension ceiling —
   intact.

Verification: `python3 -m compileall -q test_helpers test_suite` succeeds (exit 0). Citation checker
(literal whitespace-normalised grep of every quoted fragment >=25 chars against workspace/PRD.md) —
0 issues on all 19 files in test_suite/; one real defect found and fixed during the pass (test_09's
§3.8 withdrawal quote had dropped "so a corrected filing can be made"). Unused-import scan clean
(fixed ApiErrorId and build_context in test_03, four unused header/assert helpers in test_16, removed
the unused real_estate_officer parameter from TestAwardCascade._two_issued_solicitations in test_04
and its four call sites). Every ApiErrorId.* member and every api.<method>( call resolves; every
module imports cleanly; all money fields are emitted as JSON ints. Nothing under
workspace/implementation/ was created, modified, or read.

## Step 7: Run tests and iterate — 2026-09-04T04:10:00.000Z

Two iterations of the parallel 8-round stability sweep (`--isolation per-test-server --timeout 120
--test-timeout 30`, all 8 rounds launched concurrently under `setsid nohup`, joined with `wait`,
diagnosed only from the per-round `results.$i.json` — never from the spliced `sweep.log`).

| iteration | total | passed | failed | errors | union of failing tests |
|---|---|---|---|---|---|
| 1 | 111 | 106 | 5 | 0 | 5 (identical in all 8 rounds — no flakiness) |
| 2 | 111 | 111 | 0 | 0 | **0 — clean in all 8 rounds** |

No test was deleted: every failing assertion traced to a rule stated verbatim in `PRD.md` (STEP 1a
coverage and STEP 1b unique derivability both passed for all 5), so all 5 were STEP 2 test bugs. No
assertion was weakened, relaxed, skipped or xfailed. No implementation change was needed — the server
was correct on all 5.

### `test_helpers/` fixes
None. All four defects lived in the test files' own local setup helpers, not in the shared fixture
layer.

### `test_suite/` fixes (4)
- `test_04_award_and_federal_rejection_cascades.py::TestAwardCascade::test_the_site_transition_cancels_the_sibling_and_rejects_its_proposal`
  — the sibling solicitation's `version` is now re-read immediately before the award instead of being
  snapshotted at issuance. PRD §3.3 ("the parent solicitation's `responsive_proposal_count` is
  incremented by 1") is a mutation, so §2.4's "increments by exactly 1 on every mutation of that
  record" had already carried the sibling from v2 to v3 when `proposal_b` was submitted; the hop-4
  cancellation then made it v4, and the test was measuring the bump from the stale v2
  (`assert 4 == (2 + 1)`). The `version == before + 1` assertion is preserved at full strength.
- `test_06_boundary_precision.py::TestResponsiveProposalMinimum._issued_solicitation` — the shared
  setup's `api.create_site(...)` now passes `expected_status=201` to `validate_success`, per PRD §4:
  "Creating a new resource returns HTTP 201 with the created resource in `data`." The helper had been
  taking the default 200, failing both tests in the class with `Expected 200, got 201`.
- `test_11_state_machines.py::TestNegotiationPeriodTerminalStates::test_a_terminated_period_refuses_an_extension_and_keeps_its_dates`
  — the period is now opened via `negotiation_via="award"`. The fixture had used §3.5's direct grant,
  which "never selects the proposal" (the same adjudication Step 5 recorded for two other instances),
  so §3.5's termination hop 1 — "the held proposal drops `SELECTED → REJECTED`" — had no premise and
  the PRD-faithful server correctly left the proposal `SUBMITTED`. §3.4's award path does derive
  `SUBMITTED → SELECTED` (hop 1), so the asserted hop is now reachable and the
  `status == "REJECTED"` assertion stands unchanged.
- `test_13_validations.py::TestClockExpiryBlocksSubmission::test_moving_past_the_end_date_expires_the_period_and_blocks_the_submission`
  — same fixture switch to `negotiation_via="award"`, for the same reason with respect to §2.5's
  expiry hop: "the proposal each newly expired period was holding drops from `SELECTED` to
  `REJECTED`".

### `implementation/` fixes
None. Nothing was added, removed or weakened. Storage re-verified as process-local in-memory dicts
only — `store.py` boots completely empty with the logical clock at `2026-08-01T00:00:00Z`, no sqlite
file, no JSON dump, no `/tmp` cache, and `start.sh` `exec`s the app in the foreground so per-test-server
re-invocation wipes every byte of state.

Two orderings were noticed but deliberately left alone because no failing test exercises them and
neither is uniquely derivable: `routes_agreement.submit_for_review` checks valuation-CERTIFIED before
period-liveness (§3.7's narrative lists the period first, §2.11 #11 lists valuation certification
first), and `routes_federal.file_disposition` checks `negotiation_status` before
`federal_approval_status` (§3.8's narrative lists federal first).

Artifacts: `results.1.json` … `results.8.json` left in place under `workspace/implementation/`.
`__pycache__` removed from `test_helpers/`, `test_suite/` and `workspace/implementation/`.

## Step 8: Finalize PRD — 2026-09-04T04:02:00.000Z

Step 8 was NOT skipped: Step 7 recorded 4 `test_suite/` fixes, so the zero-diff skip condition did not
hold (though it did record 0 deletions, 0 `test_helpers/` fixes and 0 `implementation/` fixes, which is
why the edit count is small). The Step 7 worklog entry above was inlined verbatim as `<step_7_diff>`.

Subagent summary (verbatim):

`PRD_FINALIZED.md` written. 445 lines -> 445 lines (0.0% line delta); 94,190 -> 94,889 chars (+0.74%);
3 of 445 lines changed. All three edits are in-paragraph prose revisions; no sections, tables, or error
codes were added.

Changes:
- §3.8 (federal disposition filing) — revise — the "Three preconditions" list now evaluates
  `negotiation_status` (ERR_AGREEMENT_NOT_IN_REVIEW) before `federal_approval_status`
  (ERR_FEDERAL_APPROVAL_PENDING), matching the code; the original narrative listed federal first. —
  implementation/routes_federal.py:32 vs :35
- §3.7 (submit for review) — revise — the five-check list now places the valuation-CERTIFIED
  referential check before the negotiation-period liveness check, and says so explicitly ("before the
  negotiation-period liveness check that follows and before either fiscal check"); the original
  narrative put period liveness second, contradicting §2.11 #11's own "valuation certification status
  ... then negotiation-period liveness". — implementation/routes_agreement.py:182 vs :184
- §3.5 (direct grant) — insert — one clause pinning that a directly granted period leaves the named
  proposal in the SUBMITTED/SHORTLISTED status it held (only §3.4's award hop 1 ever writes SELECTED),
  and that the SELECTED -> REJECTED drop on termination and on clock expiry therefore fires only when
  the held proposal is actually SELECTED. — implementation/routes_negotiation.py:38-53 (no proposal
  write), guards at :103 and :137, sole SELECTED writer at routes_solicitation.py:206

Pre-edit search log:
- Edit 1 — §3.8 ordering. (a) Subject: relative order of the two agreement state-dimension checks on an
  endpoint. (b) Enumerated: routes_federal.file_disposition (32, 35), routes_federal.record_determination
  / withdraw_disposition (no dimension gate beyond determination != PENDING),
  routes_agreement.execute_agreement (238 negotiation -> 240 federal, already matching §3.7's stated
  order), routes_ops staging decision (200: only negotiation_status), routes_reads (filters only);
  grepped negotiation_status|federal_approval_status across all route modules. (c) Wording scoped with
  "on this endpoint they are evaluated in the order given here" so it cannot be read as a global rule
  that would invert §3.7's execute ordering.
- Edit 2 — §3.7 ordering. (a) Subject: valuation-certification vs negotiation-period-liveness
  precedence. (b) Enumerated: routes_agreement.submit_for_review (178-192), _require_live_period (21-32),
  routes_agreement.draft_agreement (79-87 — valuation/site alignment then period liveness, no
  certification check at all), §2.11 items 9/11/13/14 and its three precedence-pair callouts, routes_ops
  (no valuation check). (c) Anchored the claim to "the referential group of §2.11" and to this
  endpoint's five-check list rather than asserting a universal cert-before-period rule, since drafting
  performs no certification check; the pre-existing "before either fiscal check" guarantee and §2.11's
  callout are preserved verbatim in force.
- Edit 3 — §3.5 direct grant / proposal status. (a) Subject: which operations write proposal `status`,
  specifically SELECTED. (b) Enumerated via `grep -n SELECTED *.py` plus reads:
  routes_solicitation.award_solicitation:206 (the only writer of SELECTED),
  routes_solicitation.submit_proposal:122 (SUBMITTED), shortlist_proposal:139, award's non-awarded
  rejection loop (225-228, from responsive statuses), common.cancel_site_solicitations:190-193
  (responsive -> REJECTED), routes_negotiation.grant_period (writes no proposal field),
  terminate_period:103 and set_clock:137 (both guarded on == "SELECTED"), and
  routes_agreement.draft_agreement (imposes no proposal-status precondition). (c) Wording deliberately
  widened/softened twice: it speaks of "any rule that drops the proposal a period was holding from
  SELECTED to REJECTED" rather than naming a closed list of hops, and it says nothing about which
  statuses may back an agreement — drafting accepts a merely SUBMITTED proposal, so a stronger claim
  would have created a fresh mismatch.

Items intentionally left unedited: test_04 sibling-solicitation `version` snapshot (pure test bug; §3.3
increment + §2.4 per-mutation bump already determine v2->v3 then v3->v4 —
routes_solicitation.py:126, common.refresh_responsive_count); test_06 `expected_status=201` on
create_site (pure fixture bug; §4's opening sentence already states creates return 201); test_11 /
test_13 `negotiation_via="award"` fixture switch (the underlying adjudication is now pinned by Edit 3;
the REJECTED assertions were already PRD-determined); storage/clock re-verification (§2.5 already pins
the pre-set instant 2026-08-01T00:00:00Z, store.py matches).

## Step 9: Complete PRD — 2026-09-04T04:35:00.000Z

Step 9 always runs. Because a single-subagent full scan of a 445-line PRD against a 2,700-line
implementation has previously produced a byte-identical no-op output, this step was deliberately split
into THREE SEQUENTIAL file-partitioned passes, each editing `workspace/PRD_COMPLETED.md` in place
(pass 1 did the `cp` from PRD_FINALIZED.md; passes 2 and 3 were explicitly forbidden to re-copy it).
Each pass owned a disjoint slice of `implementation/` but was allowed to read the shared helper modules,
and each was required to keep its wording consistent with impl paths outside its own partition.

Result: `PRD_FINALIZED.md` 445 lines / 94,889 chars -> `PRD_COMPLETED.md` 451 lines / 110,469 chars
(+6 lines, +15,580 chars, +16.4%). Verified NOT byte-identical to PRD_FINALIZED.md, and the file still
ends on the complete `## 5. Error Code Catalogue` table (55 rows, last row `ERR_BELOW_PERMISSIBLE_FLOOR`).
Total across the three passes: **45 ambiguity-pins, 7 mismatch-revisions (52 change sites)**.

### Pass 1 — routes_sites.py / routes_solicitation.py / routes_negotiation.py (15 pins, 2 mismatches)
445 -> 445 lines, 94,889 -> 97,758 chars. Changes: §2.5 clock accepts any well-formed instant incl. a
backwards move (nothing un-expires), `expired_negotiation_period_ids` ordered by period creation, and
the clock is set *before* the expiry sweep so touched records record the new instant. §2.7/§3.2
(MISMATCH) the federal-interest basis is pinned from the most recently *recorded* appraisal — a DRAFT
determination already governs it — and "no certified valuation yet" became "no valuation recorded yet".
§3.1 the LOCAL_ONLY/`federal_interest_pct` rule is a shape check ahead of the duplicate-`site_code`
test, `site_code` uniqueness is exact/case-sensitive, and recording an assessment is not gated on site
status (CONVEYED included). §3.3 `legal_name`/`contact_email` are string-checked only (no email format);
drafting a solicitation leaves the site `version` unchanged; the affordable-minimum test compares the
*rounded* `affordable_pct` and `affordable_units` may exceed `total_units`; proposal submission bumps the
solicitation `version` by 1 and multiple proposals per developer per solicitation are allowed;
shortlisting's no-op count refresh does not bump `version`. §3.4 `deviation_justification` must be
non-empty after trimming and the rank test runs last of six; the awarded solicitation's own
`responsive_proposal_count` refreshes to 0 with no extra bump, and the response is HTTP 200 with the
solicitation (not the new period). §3.5 direct grant checks no proposal<->path-site alignment;
extension's four refusals run status -> interval -> overlap -> ceiling; termination's executed-agreement
test precedes the period-status test (a CONVERTED period reports ERR_INVALID_SITE_STATE).

### Pass 2 — routes_agreement.py / routes_federal.py / routes_ops.py (16 pins, 4 mismatches)
445 -> 445 lines, 97,758 -> 103,564 chars. Changes: §3.6 committed affordable share rounded half up to
2dp and compared at that precision; when several live periods hold the same proposal the
earliest-created one is consulted (globally); drafting writes nothing outside the new record and the
agreement is created at version 1 with money already filled; (MISMATCH) amendment re-applies the
structure-conditional money rule to *effective* values as a shape rule so it outranks the
`negotiation_status` test, and non-listed fields are ignored; the federal dimension in any state other
than FTA_REJECTED is untouched by an amendment, exactly one version bump per amendment even an empty
one. §3.7 submit-for-review neither tests nor writes `federal_approval_status`; a board revision request
writes only the agreement (leaves `board_resolution_number`, the valuation, staging windows, the federal
dimension and `submitted_by_user_id` alone); `execution_date` is any non-empty trimmed string stored
verbatim; (MISMATCH) execution does not re-test period liveness and the -> CONVERTED hop simply does not
fire when no live period holds the proposal. §3.8 the NOT_SUBMITTED filing gate rejects every other
value including NOT_REQUIRED; the unencumbered comparison is strict; accepted `determination` inputs are
only APPROVED / APPROVED_WITH_CONDITIONS / REJECTED; `condition_notes` must be non-empty once trimmed;
(MISMATCH) the `revision_notes` prefix write and `board_resolution_number` clearing belong to the
BOARD_APPROVED branch only — hops 3a/3b/4 fire only on that branch, an AGENCY_REVIEW rejection moves the
federal dimension and hop 5 alone, hop 2 is one version bump, windows visited in `created_at` order; a
filed request opens with `condition_notes` null as well as `determined_at`. §3.9 recording a facility
replacement is gated on neither agreement dimension and does not bump the agreement; an explicit
DEFICIENT report records DEFICIENT whatever the deficit and a DEFICIENT -> COMPLETE report with a
surviving deficit re-records DEFICIENT, every accepted report bumps `version`; shared-facility
registration is not gated on site status and does not bump the site; (MISMATCH) the staging envelope
comes from the earliest-created period matching the proposal *whatever its status*, `end_at` exactly
equal to the closing instant is INSIDE the envelope (the PRD had said excluded), and a proposal no
period ever held yields ERR_STAGING_WINDOW_OUTSIDE_TERM; line items are stored/echoed as exactly
`description` + `cost_cents` in submitted order and posting bumps neither facility nor agreement.

### Pass 3 — routes_reads.py + app.py / envelope.py / shape.py / authz.py / errors.py / store.py / enums.py + residual calc/common (14 pins, 1 mismatch)
445 -> 451 lines, 103,564 -> 110,469 chars. Changes: §2.1 an auth header present but empty counts as
absent, role names matched exactly/case-sensitively. §2.2 `api_request_id` is `req_` + exactly 20 chars
A-Z0-9 regenerated per response including errors and never persisted; `api_request_timestamp` comes from
the HOST WALL CLOCK not the logical clock (verified live: envelope read 2026-09-04 while the logical
clock sat at 2026-08-01); `message` is advisory with unpinned wording. §2.3 non-integer-literal `limit`
rejected (whitespace tolerated), negative `offset` rejected, no `offset` ceiling, empty-valued param ==
omitted, single-resource reads never read or validate paging, exact `has_more` formula; null-`rank`
proposals sort after all ranked ones; the final tie-break for every ordering is the hidden insertion
sequence (never the UUID) because records share `created_at` between clock moves, with the assessment
list the lone `id` exception; filters are conjunctive, an out-of-set enum filter is ERR_INVALID_REQUEST
422 (not an empty page) and being a shape check outranks the path parent's existence check, id filters
are exact-match and never existence-checked (unknown id -> empty page, not 404), unknown query params
ignored. §2.4 `id` is a random v4 UUID in canonical lower-case hyphenated form, `created_at` from the
logical clock, the internal insertion sequence never serialised. §2.5 `to_iso8601` converts an offset to
UTC, reads offset-naive as UTC, accepts bare YYYY-MM-DD as midnight UTC; `current_utc` uses the 3-digit
form. §2.6 all arithmetic in exact decimal, never binary float, so half-cent cases always round up.
§2.9 `GET /jda/developers/{id}` reports ERR_DEVELOPER_NOT_FOUND 404. §2.11 pt 3 explicit null ==
absent, strict types (bool != int, string != number), which fields are integer-only vs accept fractions,
required free-text accepts "" except the five that demand non-empty, unnamed body fields ignored, and an
absent / unparseable / non-object / no-content-type body reads as {} -> ERR_INVALID_REQUEST. §3.4 rank
ties at the same logical instant fall to insertion order. §5 intro (MISMATCH) unknown route -> 404
ERR_NOT_FOUND (the one identifier outside the catalogue), trailing slash resolves to the same route,
unsupported method -> 405 with ERR_INVALID_REQUEST (the one case that id is not 422), server fault ->
500 with ERR_INVALID_REQUEST, all using the §2.2 error envelope.

§5 error-table audit (pass 3, programmatic diff against `errors.py:ERROR_STATUS`): 55/55 rows matched on
both id and HTTP status, zero corrections needed; no error_id in errors.py is missing from §5, no §5 row
is absent from errors.py, and the row order matches the dict order. The only identifier the app emits
outside the map is ERR_NOT_FOUND (unknown route, app.py:46), documented in §5 prose rather than as a
56th row so the 55-row invariant holds.

### Final state
Step 9 touched no code, so the Step 7 green sweep stands. Independently re-verified from the on-disk
artifacts: `workspace/implementation/results.{1..8}.json` all report 111/111 passed, 0 failed, 0 errors.
`__pycache__` removed from all three code directories. Pipeline complete.
