# Worklog — task_1547_enrollment_management_yield_modeling

## Step 1: Create Task Directory — 2026-08-13T20:22:00.000Z

Task directory `tasks/task_1547_enrollment_management_yield_modeling/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher. Step 1 treated as DONE per command args; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T21:25:00.000Z

Scaffold generation complete for task 1547. All three files written to `/home/ubuntu/github/CodingPRD/tasks/task_1547_enrollment_management_yield_modeling/` and the linter is clean on the final pass.

**Lint verdict (verbatim):**
```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    36
  §1.1 entities declared:     9
  §1.8 instances scanned:     18
  §1.9 instances scanned:     53
  Calls scanned (§1.8+§1.9):  1010
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**Counts**
- Entities: 9 (AdmissionCycle, Program, Applicant, Application, CommitteeReview, AidOffer, Deposit, WaitlistEntry, MeltIntervention)
- State machines: 8 (all entities except AidOffer vs... all 9 entities except none — every entity except AdmissionCycle/Program… precisely: Cycle, Applicant, Application, CommitteeReview, AidOffer, Deposit, WaitlistEntry, MeltIntervention; Program uses a computed posture instead of a stored machine)
- Calculations: 6 (yield_forecast, melt_risk_score, aid_leveraging_award, aid_package_total, waitlist_rank_score, funnel_conversion_report)
- Endpoints: 36 (incl. `POST /_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default)
- Errors: 32; Validations: 9 priority tiers; Roles: 6 (Applicant is entity_backed; others opaque); Concurrency rules: 2 (OCC on Application.version for aid-offer create-with-supersede, OCC on Program.version for PATCH)
- §1.8 difficulty instances: 18 (exactly 2 per rule × 9 rules)
- §1.9 corner instances: 53 active + 3 excluded_because stubs (56 total); names unique across the union of both files

**Notable design decisions**
- Archetype: quota/allocation (program seats + scholarship budget as conserved ledgers) blended with multi-party negotiation (committee reads with quorum 2 gating decisions). Flat topology (FK references, filtered-list reverse GETs), cyclic state shape, peer_roles RBAC.
- The two non-linear machines (Rule 3): Application's committee send-back loop (COMMITTEE_REVIEW→IN_REVIEW with review_round bump + ASSIGNED-read cancellation) and AidOffer's negotiation cycle (OFFERED↔REVISION_REQUESTED, where re-offer recomputes the award against current budget — a patch-down from 3M to 1M recomputes 2.5M → 1.0M).
- Cascades (Rule 4): melt-sweep chain of depth 4 (melt → deposit forfeit → posture flip → conditional auto waitlist activation gated on `auto_waitlist_activation`) and aid-revoke chain of depth 3 ending in melt-risk threshold crossing (0.5500 → 0.7500 → auto-intervention).
- Boundary arithmetic pre-computed as literals: merit tier 90.00 inclusive (1,750,000 vs 1,000,000 at 89.99), deposit capacity `>=` rejection, melt-risk exactly 0.7000 creating an intervention vs 0.6999 not, funnel overall rate rounded once (0.2222, not the 0.2500 average-of-rounded).
- Two interval semantics for Rule 8: pure half-open overlap on reader review windows vs 15-minute post-buffer gap on advisor call/meeting schedules (EMAIL_CAMPAIGN and AUTO_QUEUE exempt).
- Conserved invariants (Rule 9) pinned as Program field formulas: `capacity_seats == deposited_count + enrolled_count + seats_open` and `scholarship_budget_cents == committed + available`, each exercised through a forward/compensating round trip.
- REVISION_REQUESTED deliberately releases funds from committed (only OFFERED+ACCEPTED count) — documented in the state machine so the re-offer formula is well-defined.

## Step 3: Copy Shared Files — 2026-08-13T21:27:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1547_enrollment_management_yield_modeling/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-13T21:45:00.000Z

PRD generated and verified. Output: `/home/ubuntu/github/CodingPRD/tasks/task_1547_enrollment_management_yield_modeling/workspace/PRD.md` (272 lines). The two forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped, or referenced — generation drew exclusively from `SCAFFOLD.yaml`, the skill spec, and the fixed §2.2 verbatim block.

**Section list:** 1. Introduction (2 paragraphs) · 2. Global Specifications with nine subsections (2.1 RBAC incl. per-role identity prose, 2.2 Response Structure verbatim, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Conserved Ledgers & Intake Posture, 2.7 Rounding Conventions, 2.8 OCC, 2.9 Validation Cascade Ordering) · 3. Business Logic with nine domain-derived subsections (cycles, programs, inquiry/application intake, committee reads & decisions, aid leveraging, deposits/enrollment/withdrawal, summer melt, waitlist, forecasting/funnel reports) · 4. Endpoint Definitions (36-row, 4-column table matching all 36 scaffold endpoints) · 5. Error Code Catalogue (32-row, 2-column table matching all 32 scaffold errors).

**Hard contract reports:**

```
Field coverage check:
- entities[].fields + common fields: 56 required, 56 present, 0 missing
- endpoints[].input/query_params: 14 required, 14 present, 0 missing (70 total incl. entity set)
- path params: 9 required, 9 present in §4 table, 0 missing
- endpoint output fields (informational): 14 required, 14 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 9 checked, 9 expressed in the ordered §2.9 cascade prose (with masking semantics stated), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write_endpoint + expected_application_version/expected_program_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 42 checked, 42 fully expressed (all from/to states, preconditions paired with error ids, side effects incl. close/melt/withdraw/supersede cascades), 0 missing
- calculations[]: 6 checked, 6 fully expressed in precise prose (yield_forecast both variants, melt_risk_score both clock variants with per-product rounding and 0.70 threshold side effect, aid_leveraging_award tiers/caps/eligibility-before-budget ordering, aid_package_total never-re-rounded sum, waitlist_rank_score 0.6/0.4 weights, funnel_conversion_report rounded-once overall), 0 missing
- validations[] conditions: 9 checked, all 32 error ids matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: all expressed (clock sweep, version increments, counter recomputes, filter query params per listing), 0 missing
- entities[].fields[] structured content: defaults and boundary semantics reconstructible (auto_waitlist_activation default false, refund_amount_cents null/amount/0 tri-state, review_round init 1, inclusive deposit deadline, capacity == rejects/==-1 accepts, half-open review windows, 15-minute advisor buffer with AUTO_QUEUE/EMAIL_CAMPAIGN exemptions), 0 missing
- sibling-branch symmetry: decision triad (ADMITTED/DENIED/WAITLISTED), withdrawal ladder across six states, aid-offer transition octet, and melt/withdraw auto-activation twins all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 505
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

All three contracts PASS; §2.2 is byte-identical to the canonical block; enum/state values and all numeric constants (band probabilities, melt weights, merit/need caps, quorum of two, thirty-day time factor, seven-day auto-intervention window) verified present.

## Step 5: Generate Unit Tests — 2026-08-13T22:30:00.000Z

All 86 tests collect cleanly. Generation complete.

### Queue A — Difficulty (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`): 36 tests
All 18 instances covered with exactly 2 tests each (zero shortfalls):
- `dual_variant_calc` ×2 instances → 4 tests (forecast historical vs aid-adjusted; melt-risk standard vs summer-window)
- `combinatorial_formula` ×2 → 4 (need-based budget-capped award; funnel overall rounded once)
- `non_linear_state_machine` ×2 → 4 (committee send-back loop; aid revision/re-offer recompute)
- `transitive_cascade` ×2 → 4 (melt-sweep → waitlist auto-activation; aid-revoke → melt-risk threshold crossing)
- `priority_pair_validation_conflict` ×2 → 4 (state beats fiscal on deposits; temporal beats score-range on submit)
- `boundary_precision_check` ×2 → 4 (capacity `==` rejects / `==capacity-1` accepts; merit tier 90.00 vs 89.99)
- `cross_entity_state_dependency` ×2 → 4 (quorum gate; unresolved-applications release gate)
- `resource_temporal_overlap` ×2 → 4 (half-open reader windows; advisor 15-minute buffer)
- `compensating_invariant` ×2 → 4 (seat ledger round-trip; scholarship ledger round-trip)

### Queue B — Corner (`SCAFFOLD_CORNER_DESIGN.yaml`): 50 tests
- `entities`: 8 · `state_machines`: 12 · `calculations`: 3 · `validations`: 15 · `endpoints`: 2 · `rbac`: 5 · `cross_cutting_layers`: 4 · `consistency_model`: 1
- The 3 `excluded_because` stubs were not translated; their difficulty cross-references all resolve.

### Skipped instances (3), with reasons
1. `Corner/entities/create_cycle_missing_required_field_rejected` — PRD never names `ERR_INVALID_REQUEST` as the outcome of a missing field on cycle create (its only `ERR_INVALID_REQUEST` triggers are the intervention window/outcome rules); error_id and status not uniquely derivable.
2. `Corner/entities/create_applicant_invalid_enum_rejected` — same gap: no PRD prose pins `ERR_INVALID_REQUEST` for an invalid `applicant_type` enum member.
3. `Corner/validations/melt_sweep_wrong_phase_rejected` — PRD §3.7 says the sweep is "state-gated" but never enumerates which cycle statuses permit it, so rejection at `DECISIONS_RELEASED` is not uniquely derivable (the success direction at `ENROLLMENT_TRACKING` is still exercised by the difficulty melt-sweep tests).

### Files
- `test_helpers/`: `__init__.py`, `types.py`, `api_client.py` (35 endpoint methods), `api_errors.py` (32-error catalog registered with the framework), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (per-instance `make_applicant_headers`/`make_reader_headers` for the entity-backed/identity-pinned roles), `fixtures.py` (composite chains: open-cycle setup, drive-to-admitted, waitlisted/deposited builders, aid-offer helpers).
- `test_suite/`: `conftest.py`, `test_01_cycle_lifecycle.py` (6), `test_02_programs_auth_rbac_envelope.py` (13), `test_03_applicants_and_applications.py` (9), `test_04_committee_review_workflow.py` (12), `test_05_aid_offers.py` (15), `test_06_deposits_melt_and_interventions.py` (17), `test_07_waitlist.py` (7), `test_08_forecast_and_funnel_reports.py` (7).

### Verification performed
- All files byte-compile; `test_helpers` imports cleanly; `pytest --collect-only` collects exactly 86 tests.
- Tag audit: every `Design:` line resolves to a real instance; every difficulty instance has ≥2 tests; every translated corner instance has ≥1; each docstring ends with exactly one tag.
- Citation audit: every quoted PRD passage in every docstring survives a whitespace-normalized literal match against `workspace/PRD.md` (0 failures).
- Two PRD-underivability adjustments inside otherwise-valid instances: `intake_posture == OPEN` assertions were dropped where the recipe creates the program while the cycle is still `SETUP` (§2.6 defines no posture branch for `SETUP`), and initial-`version == 1` literals were replaced with captured relative checks (`v+1`, PRD §3.2/§3.5 "increments by one") since the PRD never pins the initial version value.

## Step 6: Generate Implementation — 2026-08-13T22:05:00.000Z

Fresh boot returns 404 with the correct error envelope. The implementation is complete and booting cleanly.

### File list (all under `workspace/implementation/`)

- `start.sh` — foreground launcher, guarded pip install, `exec python3 app.py`
- `requirements.txt` — `flask>=3.0`
- `app.py` — Flask app factory, error handlers, blueprint registration, `0.0.0.0:$PORT`
- `errors.py` — `ApiError` + all 32 error-ID constants from the catalog
- `db.py` — `Store` (9 entity dicts, all empty at boot), logical `Clock` (default `2026-08-01T00:00:00Z`), ISO-8601 ms-precision timestamp helpers
- `response.py` — envelope helpers producing `{meta:{api_request_id, api_request_timestamp[,limit,offset,total_count,has_more]}, response_type, data}`
- `middleware.py` — `X-User-ID`/`X-User-Role` extraction, six-role check, role gating
- `services/serializers.py` — per-entity serializers + `touch()` (version++/updated_at refresh)
- `services/derived.py` — all calculations: `recompute_program`, `recompute_cycle`, `recompute_application_aid_fields`, `recompute_submitted_read_count`, `recompute_melt_risk` (both variants, threshold auto-intervention), `compute_aid_award` (MERIT/NEED_BASED tiers, fund caps, half-up cents), `compute_waitlist_rank_score`, `select_top_waitlist_entry` (rank_score DESC, submitted_at ASC), `activate_waitlist_entry`, `cancel_assigned_reviews`, `revoke_aid_offers`, `maybe_auto_activate`, `sweep_melt_risk_all_deposited`
- `routes/clock.py` — `POST /_clock/set_current_utc`
- `routes/cycles.py` — cycles CRUD + advance + forecast + funnel-report + melt-sweep
- `routes/programs.py` — programs CRUD + OCC-guarded PATCH
- `routes/applicants.py` — applicant intake + reads
- `routes/applications.py` — application submit, get, list, full transition endpoint incl. `_melt_application` and `_withdraw_from_deposited` cascades
- `routes/reviews.py` — review create (with dup-reader + half-open window overlap), get, list, submit
- `routes/aid_offers.py` — offer create (OCC + supersede), get, list, transition (incl. re-offer recompute)
- `routes/deposits.py` — deposit create (6-step cascade: ownership → state → clock → amount → phase → capacity), get, list
- `routes/waitlist.py` — waitlist-entries get/list + `POST /waitlist-activations`
- `routes/interventions.py` — intervention create (15-min advisor buffer, AUTO_QUEUE/EMAIL_CAMPAIGN exempt), get, list, transition

### Endpoint coverage: 36 / 36
1 clock + 6 cycle + 4 program + 3 applicant + 4 application + 4 review + 4 aid-offer + 3 deposit + 3 waitlist + 4 intervention = **36**, matching the endpoint table.

### State machine coverage: 8 / 8
- **AdmissionCycle** — SETUP→OPEN→REVIEW_CLOSED→DECISIONS_RELEASED→ENROLLMENT_TRACKING→CLOSED with all four clock preconditions, no-programs and unresolved-applications gates, close cascade (waitlist expire, applications to DENIED, interventions cancel)
- **Applicant** — INQUIRY→APPLIED absorbing auto-flip on first application
- **Application** — 14 transitions across SUBMITTED/IN_REVIEW/COMMITTEE_REVIEW/DECISION_PENDING/ADMITTED/DEPOSITED/WAITLISTED → ADMITTED/DENIED/WAITLISTED/ENROLLED/MELTED/WITHDRAWN incl. send-back (review_round++, cancels ASSIGNED), quorum gate, posture+phase gates on admit, ownership check on applicant-initiated WITHDRAWN, melt cascade, deposit-resolution-by-calendar on DEPOSITED→WITHDRAWN, conditional waitlist auto-activation on freed seats
- **CommitteeReview** — ASSIGNED→SUBMITTED (window half-open check, score range, reviewer match) and ASSIGNED→CANCELLED cascades
- **AidOffer** — OFFERED→{ACCEPTED,DECLINED,REVISION_REQUESTED,REVOKED,SUPERSEDED}, REVISION_REQUESTED→{OFFERED,REVOKED}, ACCEPTED→REVOKED, with ledger/aid-field/melt-risk recompute on every transition
- **Deposit** — PAID→REFUNDED (≤ deadline, full refund) / PAID→FORFEITED (> deadline or melt, refund 0)
- **WaitlistEntry** — ACTIVE→ACTIVATED (manual + auto), ACTIVE→EXPIRED (cycle close), ACTIVE→REMOVED (manual deny / applicant withdraw)
- **MeltIntervention** — SCHEDULED→COMPLETED (with outcome, recompute melt risk), SCHEDULED→CANCELLED (manual + enroll + close cascades)

### Calculation coverage: 6 / 6
- `yield_forecast` — historical_band + aid_adjusted variants, half-up integer projection
- `melt_risk_score` — standard vs summer_window variants selected by clock vs deposit_deadline; per-product 4-dp half-up rounding before summation; threshold auto-intervention with AUTO_QUEUE/EMAIL_CAMPAIGN/7-day window
- `aid_leveraging_award` — MERIT tiers (0.50/0.35/0.20 at 95/90/80), NEED_BASED (min(need_base, 0.60·tuition)), fund caps 2.5M/3M, min(base, available)
- `aid_package_total` — sum of ACCEPTED only, never re-rounded; aid_gap = max(0, tuition − accepted)
- `waitlist_rank_score` — 0.6·score + 0.4·(100·ADMIT_recs/submitted), 4-dp half-up
- `funnel_conversion_report` — per-source rows + overall computed from unrounded totals

### Notable implementation decisions
- **Logical clock** is a module-level singleton; default `2026-08-01T00:00:00Z`, never falls back to wall-clock. Clock set sweeps melt-risk recomputation across all DEPOSITED apps.
- **In-memory store** is module-level on `db.py`; nothing is seeded at boot — all dicts start empty so `--isolation per-test-server` restarts always begin from a clean slate.
- **`_ever_admitted` private flag** on applications implements the PRD's "ever reached ADMITTED" rule for `decisioned_count` (WITHDRAWN-from-ADMITTED/DEPOSITED counts, WITHDRAWN-from-earlier-stages does not).
- **OCC** is enforced only on the two scaffold-declared endpoints (`POST /aid-offers` with `expected_application_version`, `PATCH /programs/{id}` with `expected_program_version`) and both increment the parent's version on success.
- **Validation priority ordering** follows §2.9: auth → role/ownership → existence → OCC → state → clock → field → cross-entity → fiscal. Deposit creation sequences ownership → ADMITTED state → deposit-deadline clock → amount match → cycle phase → capacity.
- **Half-open window overlap** for both review windows and the 15-minute advisor buffer ([start, end+15min) exclusion) with `AUTO_QUEUE` and `EMAIL_CAMPAIGN` exempt.
- **Conditional auto-activation** after melt or post-deposit withdrawal only fires when `auto_waitlist_activation` is true AND the recomputed posture is OPEN; empty pool is silent per PRD.
- **Money math** uses `Decimal` with `ROUND_HALF_UP`; all rates/probabilities quantized to 4 dp; per-product rounding before summation per PRD §2.7.
- **start.sh** guards `pip install` behind `python3 -c "import flask"` so per-test reboots skip installation; verified boot-to-200 in under 3s.

## Step 7: Run Tests and Iterate — 2026-08-13T22:45:00.000Z

All 8 rounds pass 86/86. Clean sweep achieved.

- **Iterations run:** 2 (initial sweep: 81/86 in all 8 rounds with the same 5 failures; post-fix sweep: 86/86 × 8 rounds, zero failures).

- **Tests deleted:** none.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `test_suite/test_07_waitlist.py` — `TestWithdrawCascades::test_application_withdraw_cascades`: changed the standalone committee review's reader from `"reader-1"` to `"reader-committee"`. The test's setup assigned `reader-1` an ASSIGNED review with the default window, then `create_waitlisted_application` drove a second application through `reader-1`/`reader-2` with the same default window. PRD §3.4 verbatim forbids this: "the new window may not overlap another `ASSIGNED` review window **for the same reader**" (reader-global, unlike the same-application duplicate rule) — so the implementation's `ERR_REVIEWER_WINDOW_OVERLAP` was correct and the fixture setup was the bug. Reader identity is incidental to the test's assertions (withdrawal cancels ASSIGNED reads; waitlist withdrawal removes the entry).

- **Fixes applied to `implementation/`:**
  - `workspace/implementation/services/derived.py` — `activate_waitlist_entry`: fixed `NameError: name 'c' is not defined` (line 286 called `recompute_cycle(c)`; the local variable is `cycle`). Also simplified the convoluted cycle lookup to `store.cycles.get(program["cycle_id"])` guarded by the existing `if program` block. This single bug produced HTTP 500s in 4 tests: `test_sweep_melts_deposited_and_forfeits`, `test_sweep_freed_seat_auto_activates_top_waitlist_entry` (both via melt-sweep → `maybe_auto_activate` → `activate_waitlist_entry`), and `test_manual_waitlist_activation_rank_order`, `test_waitlist_tie_break_earliest_submitted` (both via `POST /waitlist-activations` → `activate_waitlist_entry`).

All 5 failures were consistent across all 8 rounds (no flakiness). After the two fixes, all 8 parallel rounds report 86/86 passed.

## Step 8: Finalize PRD — 2026-08-13T22:50:00.000Z

**Conclusion: NEITHER step_7_diff item corresponds to a PRD silence or mismatch. Both are pure bugs on behavior the PRD already pins. `PRD_FINALIZED.md` was created as a byte-identical copy of `PRD.md`** (verified: `diff -q` identical, matching md5 `18a3738bac32197ec2ad0f514771a44e`).

**Line counts / %-delta:** PRD.md = 271 lines, PRD_FINALIZED.md = 271 lines, 0.0% delta.

### Per-item reasoning

**Item 1 — `test_suite/test_07_waitlist.py` reader change (fixture fix).** Pure fixture bug; PRD already pins the rule.
- (a) Subject: scope of the review-window-overlap rule (reader-global vs. same-application).
- (b) Impl paths enumerated: `implementation/routes/reviews.py:60-69` — the overlap check loops over **all** reviews in the store filtered only by `reader_id` and `status == "ASSIGNED"`, with no `application_id` filter, i.e. reader-global. Half-open semantics (`ws < ee and es < we`) permit exact end-equals-start adjacency.
- (c) No PRD wording change: PRD §3.4 (line 133) already states verbatim "the new window may not overlap another `ASSIGNED` review window **for the same reader** — the windows being half-open, a new window whose start exactly equals an existing window's end is permitted, while any true overlap is rejected with `ERR_REVIEWER_WINDOW_OVERLAP`". The absence of a same-application qualifier (in contrast to the adjacent duplicate-reader rule, which is explicitly scoped "for the same application") uniquely determines the reader-global semantics the implementation exhibits. The test fixture violated the PRD; the implementation was correct.

**Item 2 — `services/derived.py` `activate_waitlist_entry` NameError (implementation fix).** Pure code crash bug; PRD already pins the intended behavior.
- (a) Subject: waitlist activation cascade (entry/application transition + counter recomputes).
- (b) Impl paths enumerated — every caller of the fixed function: `implementation/routes/waitlist.py:72-78` (manual `POST /waitlist-activations`), `implementation/routes/applications.py:165` (`_melt_application` → `maybe_auto_activate`), `implementation/routes/applications.py:194` (`_withdraw_from_deposited` → `maybe_auto_activate`), `implementation/routes/applications.py:256` (direct `WAITLISTED → ADMITTED` transition endpoint), and `implementation/services/derived.py:312-323` (`maybe_auto_activate` itself). The fix replaced a bare `NameError` (`recompute_cycle(c)`, HTTP 500 — a crash, not a behavioral choice) with a guarded `store.cycles.get(program["cycle_id"])` + `recompute_cycle(cycle)`. Resulting observable behavior: entry `ACTIVE → ACTIVATED`, application `WAITLISTED → ADMITTED` with ever-admitted flagged, program counters recompute, cycle funnel aggregates recompute (idempotent; every caller also recomputes the cycle itself).
- (c) No PRD wording change: PRD §3.8 (line 181) pins "Activation moves the selected entry from `ACTIVE` to `ACTIVATED`, moves its application from `WAITLISTED` to `ADMITTED`, increments the program's `admitted_count` by one, and re-derives posture"; §3.8 (line 183) pins the same for the auto-activation path; §3.1 (line 113) pins that cycle counters "are maintained live thereafter" with `decisioned_count` counting "any application that ever reached `ADMITTED`" — which uniquely determines the cycle-side recompute outcome the fixed code produces. Nothing in the fixed behavior is undetermined by the PRD, and no wording was added that could mis-describe any of the five enumerated call paths.

**Deliverable:** `workspace/PRD_FINALIZED.md` (byte-identical to PRD.md).

## Step 9: Complete PRD — 2026-08-13T23:08:05.000Z

`PRD_COMPLETED.md` is written at `workspace/PRD_COMPLETED.md`.

## Summary

- **Source vs output**: `PRD_FINALIZED.md` 271 lines / 50,027 chars → `PRD_COMPLETED.md` 275 lines / 56,260 chars (**+4 lines, +6,233 chars**; 44 changed diff lines across 21 hunks, all in-paragraph inserts/revisions, no new sections).
- **Counts**: 16 ambiguity-pins, 4 mismatch-revisions.

### Changes (one bullet each)

- §2.2 — insert — ambiguity — envelope `api_request_timestamp` pinned to the server-side logical clock, not wall-clock — `implementation/response.py:14-17`, `implementation/db.py:55-56`.
- §2.2 — insert — ambiguity — unrecognized paths answer `ERR_NOT_FOUND` (404); unsupported methods answer `ERR_INVALID_REQUEST` with HTTP 405 — `implementation/app.py:38-44`.
- §2.3 — revise — ambiguity — `limit` is clamped into [1,100] and `offset` floored at 0 (not rejected); non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (400); list sort ties break by `id` ascending; `total_count` counts the filtered set; `has_more` ⟺ `offset`+`limit` < `total_count` — `implementation/routes/programs.py:90-106` (same pattern in all list endpoints), `implementation/response.py:23`.
- §2.5 — revise — mismatch — replaced the blanket "any mutation refreshes `updated_at`/increments `version` on each resource it touches" with impl's real rule: `version` starts at 1; own-state writes and named parent-bump cases (aid-offer create/transition → app+program; review submit / intervention completion → app; admission, deposit, enrollment, withdrawal from ADMITTED, waitlist activation → program) bump versions; derived-field recomputation alone never does (cycle version advances only on advance; clock sweep rewrites `melt_risk_score` without bumping app versions) — `implementation/services/serializers.py:5-8`, `implementation/services/derived.py:111-201`, `implementation/routes/cycles.py:160-162`.
- §2.6 — insert — ambiguity — posture reports `PAUSED` while the cycle is still in `SETUP` — `implementation/services/derived.py:51-53`.
- §2.9 — insert — ambiguity — structural failures (missing required field, bad enum, unparseable timestamp, non-integer pagination, window end ≤ start) → `ERR_INVALID_REQUEST` (400), evaluated after auth/authz/resource-resolution and ahead of the numbered tiers, with two exceptions (review submission validates scores/recommendation after the window check; intervention completion validates `outcome` after the state gate); absent body foreign keys fall under tier three's `ERR_NOT_FOUND` — `implementation/routes/reviews.py:145-163`, `implementation/routes/interventions.py:138-145`, `implementation/routes/waitlist.py:61-62`, `implementation/routes/applications.py:43-48`.
- §2.9 — insert — ambiguity — existence of a target resource is established before any ownership comparison; nonexistent resources answer `ERR_NOT_FOUND` even when the caller could not own them — `implementation/routes/deposits.py:26-32`, `implementation/routes/applications.py:106-108`, `implementation/routes/aid_offers.py:98-102`.
- §2.9 — insert — ambiguity — classified `ERR_TARGET_EXCEEDS_CAPACITY` and `ERR_PROGRAM_CYCLE_MISMATCH` into tier seven — `implementation/programs.py:129-134`, `implementation/routes/applications.py:62-64`.
- §3.2 — revise — ambiguity — on program update the target-vs-capacity check runs before the budget-floor check — `implementation/routes/programs.py:129-134`.
- §3.3 — revise — ambiguity — application-filing guards pinned in impl's firing order: score range → applicant/program/cycle alignment → cycle phase — `implementation/routes/applications.py:54-67`.
- §3.3 — insert — ambiguity — an applicant may hold any number of applications — `implementation/routes/applications.py:33-97` (no uniqueness check).
- §3.4 — insert — ambiguity — review assignment window end must be strictly after start, else `ERR_INVALID_REQUEST` — `implementation/routes/reviews.py:45-46`.
- §3.4 — revise — mismatch — "very first assignment" auto-move replaced: any assignment created while the application is in `IN_REVIEW` (including re-assignment after a send-back) moves it to `COMMITTEE_REVIEW`; the transition endpoint also accepts an explicit `IN_REVIEW` → `COMMITTEE_REVIEW` move — `implementation/routes/reviews.py:89-92`, `implementation/routes/applications.py:205`.
- §3.4 — insert — ambiguity — submitting a review no longer in `ASSIGNED` → `ERR_INVALID_STATE`; state and window checks precede score/recommendation validation — `implementation/routes/reviews.py:145-154`.
- §3.4 — insert — ambiguity — per-target role gating on the application transition endpoint (committee targets = `AdmissionsOfficer`-only, `ENROLLED` = `EnrollmentManager`-only, `WITHDRAWN` = officer or owning applicant), applied only after the transition itself is recognized as permitted — `implementation/routes/applications.py:261-278`.
- §3.5 — insert — ambiguity — full offer lifecycle exposed by the transition endpoint (`OFFERED`→{ACCEPTED, DECLINED, REVISION_REQUESTED, REVOKED, SUPERSEDED}; `REVISION_REQUESTED`→{OFFERED, REVOKED}; `ACCEPTED`→{REVOKED}; rest terminal/`ERR_INVALID_STATE`), per-target role gates, and manual `OFFERED`→`SUPERSEDED` with no further restriction — `implementation/routes/aid_offers.py:130-191`.
- §3.6 — revise — mismatch — dropped the claim that enrollment keeps an "explicit guard" on deposit `PAID` status; impl relies on the invariant implied by `DEPOSITED` — `implementation/routes/applications.py:294-296,355-368`.
- §3.6 — insert — ambiguity — `DEPOSITED` and `MELTED` are invalid `to_status` values on the transition endpoint (`ERR_INVALID_STATE`); only the deposit flow and melt sweep perform those moves — `implementation/routes/applications.py:235-240`.
- §3.7 — revise — ambiguity — melt-risk recompute triggers extended to every aid-offer transition (incl. revision request and manual supersede), and recompute applies only while the application is `DEPOSITED` — `implementation/services/derived.py:111-114`, `implementation/routes/aid_offers.py:187-190`.
- §3.7 — insert — ambiguity — manual intervention create naming `advisor_id` = `AUTO_QUEUE` → `ERR_INVALID_REQUEST` — `implementation/routes/interventions.py:39-41`.
- §3.7 — revise — ambiguity — melt sweep permitted only in `DECISIONS_RELEASED`/`ENROLLMENT_TRACKING`; applications processed in creation order (ties by `id`), response lists follow that order — `implementation/routes/cycles.py:254-270`.
- §3.8 — insert — ambiguity — selector's remaining ties (equal `rank_score` and `submitted_at`) resolve by entry creation order, in both manual and auto activation — `implementation/services/derived.py:252-267`.
- §3.8 — insert — ambiguity — `WAITLISTED` → `ADMITTED` also reachable via the application transition endpoint with gates entry-exists → posture → cycle phase, open to that endpoint's roles with no further restriction — `implementation/routes/applications.py:242-259`.
- §3.9 — insert — ambiguity — invalid forecast `variant` → `ERR_INVALID_REQUEST` (400) — `implementation/routes/cycles.py:170-172`.
- §3.9 — insert — ambiguity — aid-adjusted coverage ratio is 0 when the program's tuition is zero — `implementation/routes/cycles.py:193-194`.
- §3.9 — insert — ambiguity — funnel report emits rows in the fixed source order `WEB_FORM, CAMPUS_VISIT, COLLEGE_FAIR, REFERRAL, PURCHASED_LIST`, each row carrying `inquiry_source`, `inquiries`, `applied`, `conversion_rate` — `implementation/routes/cycles.py:223-247`.

Note: the endpoint table (§4), error catalogue (§5), aid formulas, melt-risk weights/rounding, deposit cascade ordering, and all role assignments were verified against the implementation and already matched — no changes needed there.

