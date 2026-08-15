# Worklog — task_1893_loan_participation_syndication

## Step 1: Create Task Directory — 2026-08-14T23:14:00.000Z

Pre-created by pipeline operator: `tasks/task_1893_loan_participation_syndication/` + `workspace/` (per command args; orchestrator did not scan tasks/ or compute indices).

## Step 2: Generate Scaffold — 2026-08-15T00:16:30.000Z

All three files exist, parse as valid YAML, and pass the official `scaffold_lint.py` with **VERDICT: clean lint** (962 calls scanned across §1.8+§1.9, zero violations, all FKs reverse-reachable).

## Summary — task_1893_loan_participation_syndication

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1893_loan_participation_syndication/`):
- `SCAFFOLD.yaml` — 2,055 lines (§1.0–§1.7 only; no design keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 928 lines (single top key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 1,299 lines (single top key `scaffold_corner_design`)

**SCAFFOLD.yaml counts:** 16 entities, 16 state machines, 11 calculations, 13 validation priorities, **82 endpoints** (incl. `POST /api/_clock/set_current_utc` with the mandated 2026-08-01T00:00:00Z default), 38 error codes, 4 roles, 3 OCC concurrency rules.

**§1.8 difficulty instances: 21** (≥18 required) — dual_variant_calc ×2, combinatorial_formula ×3 (modes a/b/c each), non_linear_state_machine ×2, transitive_cascade ×3 (depths 4/3/3, distinct triggers), priority_pair_validation_conflict ×2 (state×fiscal; referential×temporal), boundary_precision_check ×2 (bps threshold at tally_close; cents headroom at POST /api/draws), cross_entity_state_dependency ×3 (distinct pairs), resource_temporal_overlap ×2 (half-open draws vs closed reporting windows), compensating_invariant ×2 (payment-cents conservation+reversal; commitment conservation across transfers).

**§1.9 corner instances: 65** (57 real recipes + 8 excluded_because stubs pointing at §1.8), spanning all 9 claim-guide sections: entities 9, state_machines 19, calculations 9, validations 13, endpoints 3, errors 2, rbac 5, cross_cutting_layers 4, consistency_model 1.

**Design decisions for the worklog:**
- Archetype: multi-party negotiation + ledger reconciliation; flat topology, cyclic state machines, immediate consistency; roles AgentBank (opaque) / Borrower / ParticipantLender (entity-backed), plus System for cascades.
- Logical clock (default 2026-08-01T00:00:00Z) drives funding-due, voting-window, lateness, and blackout semantics — no wall-clock dependence.
- All money/assert arithmetic pre-computed with Python (e.g., waterfall 200,000 → fee 1,041 / interest 50,000 / principal 148,959; day-count divergence 30,000 vs 29,589 vs 29,000; cure 3-segment accrual 48,888; waive retro-removal 39,999 — deliberately one cent below 40,000 to pin per-segment flooring; buyback STANDARD 1,515,000 vs PENALTY 532,140).
- Consent/default tallies use commitment sums against an exit-adjusted base (voting_base snapshot minus exited commitments) — share_bps itself is floor+remainder with tie-breaks on commitment/created_at/name, never id.
- Three true-race OCC rules only (draw create on Facility.version, distribution rerun supersede on BorrowerPayment.version, transfer settle on Participant.version); everything else classified as state preconditions per §1.2.1.
- Lint found and I fixed: 4 FK reverse-reachability gaps (added `GET /api/draws` filtered list + 3 filter params) and PyYAML flow-scalar quoting for `?`-suffixed optionals and `[...]`-bearing grounds tokens.

Orchestrator note: the first scaffold subagent (aa325c5d63d33518a) terminated twice after its design sketch without writing files; a fresh subagent (a9bda2cd40bda36f8) with an explicit do-not-stop-until-verified directive completed the step, writing SCAFFOLD.yaml first, then the two design files, fixing a PyYAML flow-scalar quoting issue mid-flight.

## Step 3: Copy Shared Files — 2026-08-15T00:18:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1893_loan_participation_syndication/workspace/INSTRUCTION.md (1,424 bytes).

## Step 4: Generate PRD — 2026-08-15T00:35:00.000Z

PRD generation complete. The output file exists and is verified at `/home/ubuntu/github/CodingPRD/tasks/task_1893_loan_participation_syndication/workspace/PRD.md`.

## Summary

**PRD.md line count:** 375 lines

**Section list:**
- Title + §1 Introduction (3 paragraphs)
- §2 Global Specifications & System-Wide Principles: 2.1 User and Role-Based Access Control; 2.2 API Response Structure (verified byte-identical to the canonical `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Common Resource Properties; 2.6 Money, Basis Points, and Rounding Discipline; 2.7 Facility Aggregates, Bubble-Ups, and Cascade Discipline; 2.8 Optimistic Concurrency Control; 2.9 Validation Priority Order; 2.10 Nested Resource Retrieval and Reference Resolution
- §3 Business Logic & Workflows: 3.1 Borrower Onboarding and Facility Structuring; 3.2 Syndication: Participants, Commitments, and Pro-Rata Shares; 3.3 Draws and the Funding Window; 3.4 Interest Accrual, Day-Count Conventions, and Default Re-Rating; 3.5 Borrower Payments, the Distribution Waterfall, and Reversal; 3.6 Borrower Modifications and Consent Solicitation; 3.7 Default Declaration, Lender Voting, and Resolution; 3.8 Financial Statements and Participant Reporting Packages; 3.9 Participation Transfers and Buyback Demands
- §4 Endpoint Definitions (4-column table: Method / Path / Description / Authorized Roles)
- §5 Error Code Catalogue (2-column table: Error ID / HTTP Status)

**Coverage self-audit (vs scaffold totals):**
- **Entities: 16/16** — all 110 entity field names appear verbatim in backticks (mechanical diff: 0 missing)
- **State machines: 16/16** — every transition's from/to pair, preconditions, and side effects expressed in prose, including multi-hop cascades (default declaration 3-hop, remit 4-hop, reversal clawback 3-hop); all 54 distinct state values present
- **Calculations: 11/11** — participant_share_bps, interest_accrual (all 3 day-count variants incl. the 30/360 clamp formula and 29-day example), servicing_fee_accrual (fee-first ordering, baseline rule), waterfall_distribution (both conservation invariants, remainder order with cycling), late_funding_penalty (15 bps/day, amount-check-then-penalty order), consent_tally, default_vote_tally, default_interest_re_rate (declare/cure/waive/accelerate segmentation), buyback_price (standard vs 500-bps penalty variants), principal_reduction_allocation (oldest-first, never-id tiebreak), committed_recompute — all as operator-free precise prose
- **Validations: 13/13** priority levels expressed as an explicit ordered list in §2.9, with every rule's trigger paired to its error_id in §2/§3 narrative; all `applies_to` scopes enumerated
- **Endpoints: 82/82** rows in the §4 table with exact paths, methods, and role lists (mechanically diffed, including per-endpoint role match); all request-body keys, query/filter params, and the 15 path params present verbatim; all endpoint side effects narrated in §3
- **Errors: 38/38** — all in the §5 catalogue with correct HTTP statuses, and every error_id also mentioned in §1–§3 prose (0 missing)

**Hard contract reports:**
- Contract 1 (Field-Name Coverage): 121 required identifiers (entity fields, request-body keys, query params, path params, terms keys, envelope fields) — all present, 0 missing. PASS
- Contract 2 (Rule Coverage): 13/13 validation priorities with ordering; 3/3 OCC rules (write endpoint + `expected_*_version` field + `ERR_STALE_VERSION`/412 named, framed purely as stale-view rejection); all transitions, calculations, validation conditions, and endpoint side effects expressed; structured field content (defaults, derivations, initial values) reconstructible; sibling branches (6 modification types, 3 resolution paths, 3 day-count bases, 2 buyback variants) rendered at equal density; 48/48 targeted rule-phrase spot checks pass. PASS
- Contract 3 (§3 Path Purity): 664 backticked tokens scanned in §3 — 0 path tokens, 0 bare HTTP methods, 0 method+path combos. PASS

Constraint compliance: `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened; no other task directory was accessed.

## Step 5: Generate Unit Tests — 2026-08-15T01:15:00.000Z

Generation complete and fully verified. Summary:

## Files written (21 files, 5,069 lines)

**test_helpers/** (1,741 lines):
- `types.py` (429) — 16 entity TypedDicts + 15 status/role enums
- `api_client.py` (348) — `ApiClient(GenericApiClient)` with one method per PRD §4 endpoint (~70 methods)
- `assertions.py` (263) — per-entity `assert_*` + waterfall conservation/pool-line reconciliation checkers
- `fixtures.py` (377) — tiered composites: `setup_committed_facility`, `setup_funded_facility` (wires each settlement for its exact `due_cents`), draw/payment/run/transfer/buyback/modification helpers; OCC versions always re-read immediately before the gated write
- `api_errors.py` (90) — 38 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `factories.py` (123), `constants.py` (49), `test_users.py` (27), `__init__.py` (35)

**test_suite/** (3,328 lines): `conftest.py` + 11 test files (`test_01` syndication/setup … `test_11` RBAC/cross-cutting).

## Test counts — 100 total, all collected by pytest
- **Queue A (Difficulty): 43 tests** — all 21 instances covered with ≥2 tests each
- **Queue B (Corner): 57 tests** — all 57 non-stub instances covered with exactly 1 test each; the 8 `excluded_because:` stubs were not translated (all cross-references verified to resolve)

## Verification results
- `py_compile` passes on all 21 files; all test modules import; pytest collects 100 tests
- Tag audit: every test has exactly one `Design:` line; all 100 tags resolve to existing instance names in the design YAMLs
- Citation audit: 149 PRD quotes extracted from docstrings, all survive literal grep of PRD.md (11 initial mismatches — elisions I had placed inside quotes — were rewritten to full verbatim sentences)
- No `skip`/`skipif`/`xfail` anywhere

## Instances skipped
None. All 21 difficulty + 57 corner instances passed the PRD-first filter.

## Notable adjudications / design decisions (for worklog)
- **`draw_cancel_with_confirmed_funds_rejected`**: the recipe's single-participant setup leaves the draw SETTLED (terminal), which would make priority-6 `ERR_INVALID_STATE_TRANSITION` compete with the asserted `ERR_DRAW_HAS_CONFIRMED_FUNDS`. Restructured to two participants with only one settlement confirmed — draw stays FUNDING, so the confirmed-funds rule is the sole failing check. Claim preserved.
- **`transfer_stub_below_minimum_rejected`**: the recipe's 600,000 amount is itself below the 1,000,000 minimum (its "clears the minimum" note is wrong), so `ERR_TRANSFER_BELOW_MINIMUM` would fire instead. Used 1,100,000 from a 1,500,000 commitment (stub 400,000) so only the stub rule fails.
- **`buyback_not_funded_rejected`**: the recipe's COMMITTED-state facility would trip the priority-7 posture rule (`ERR_INVALID_STATE_TRANSITION`) before the eligibility rule. Restructured so the facility reaches FUNDING (draw created, wire never confirmed) — posture passes, demander is COMMITTED-not-FUNDED, `ERR_BUYBACK_NOT_FUNDED` uniquely derivable.
- **Version tests** (`version_increments_on_every_mutation`, borrower creation): PRD §2.5 pins "increments by one on every mutation" but never an initial value, so assertions are relative (`v_end == v0 + 3` after three commits; participant version +1 on its own commit) rather than the recipe's absolute `== 1`.
- **Draw creation in FUNDING/ACTIVE**: recipes create follow-on draws while the facility is FUNDING (headroom, window tests) and ACTIVE (oldest-draw-first), so fixtures follow the design-index semantics; no test asserts `ERR_FACILITY_NOT_COMMITTED` on those states. The only `ERR_FACILITY_NOT_COMMITTED` assertion is on a CLOSED facility, where §2.9 item 7 nominates it.
- **Entity-backed identity threading**: all ownership-gated calls use `make_borrower_headers(borrower["id"])` / `make_participant_headers(participant["id"])`; the shared `TEST_USERS` constants are used only for AgentBank (opaque) and non-ownership tests.
- Second tests per difficulty instance probe distinct facets of the same rule (e.g., ACT_360 vs BASIS_30_360 on a 6M position, supermajority exact-boundary PASSED, fee cap `min(raw_fee, amount)` branch, existing-participant transferee, INSOLVENCY borrower marking, ALLOCATED/RECEIVED reversal strengths).

## Step 6: Generate Implementation — 2026-08-15T01:15:00.000Z

Implementation complete and verified. Final summary:

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_1893_loan_participation_syndication/workspace/implementation/`)

| File | Lines | Contents |
|---|---|---|
| `start.sh` | 10 | Foreground launcher; guarded pip install (`if ! python3 -c "import flask"`); `exec python3 app.py`; reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 1 | flask>=3.0 |
| `app.py` | 55 | App factory, blueprint registration, ApiError/404/405/generic handlers |
| `store.py` | 151 | In-memory dict store (16 collections, zero seeding), logical clock (default exactly `2026-08-01T00:00:00Z`, never wall-clock), id/timestamp helpers, per-request-guarded `touch()` (one version bump per entity per request), `_seq` insertion ordering |
| `errors.py` | 162 | ApiError + all 38 catalog error constructors with exact IDs/HTTP codes |
| `responses.py` | 68 | Envelope: `meta{api_request_id, api_request_timestamp}`, `response_type` object/array/error; pagination fields `limit/offset/total_count/has_more` in meta for lists; error meta carries only id+timestamp |
| `auth.py` | 98 | X-User-ID/X-User-Role validation, role gating, strict field validators |
| `calc.py` | 455 | All 11 calculations (below) |
| `domain.py` | 147 | Exit cascade (vote voiding + tally recompute), borrower restoration, closure bubble, pagination/filter helpers |
| `routes_core.py` | 281 | clock, borrowers, facilities (+5 nested lists), participants commit/withdraw |
| `routes_funding.py` | 269 | draws (OCC, overlap, headroom), settlements (wire/confirm/mark_defaulted, late penalty) |
| `routes_payments.py` | 363 | payments, reversal (3 strengths incl. full clawback with accrual-ledger snapshot rollback), run creation (supersession), remit 4-hop cascade |
| `routes_mods.py` | 374 | modification requests (6 types, derived consent class/threshold), solicit/24h buffer/re-solicit voiding, votes, tally_close, implement per type, withdraw |
| `routes_defaults.py` | 269 | default cases (3-hop declare cascade), default votes, cure/waive/accelerate |
| `routes_reporting.py` | 215 | statements (45/90-day due dates, duplicate triple), packages (closed-interval overlap, assemble/deliver) |
| `routes_transfers.py` | 375 | transfers (all guards, OCC on transferor, conservation, exit cascade), buybacks (both price variants) |

**Endpoints: 82/82** (verified by Flask route count against the live app). **State machines: 16/16** including bubble-ups (facility STRUCTURING→SYNDICATING→COMMITTED→FUNDING→ACTIVE, COMMITTED→SYNDICATING demotion, FUNDING→COMMITTED revert on cancel, closure from ACTIVE/ACCELERATED and via cure/waive, CLOSED→ACTIVE reopen on clawback) and cascades (declare 3-hop, remit 4-hop, reversal clawback, participant exit vote-voiding). **Calculations: 11/11** — participant_share_bps (floor + remainder, commitment DESC/created_at/name ASC), interest_accrual (3 day-count bases, per-segment floor, default-window segmentation, prospective rate-change history), servicing_fee_accrual (pre-run outstanding, baseline = last_distribution_value_date else first settled draw date), waterfall_distribution (fee→interest→principal, FUNDED-only split with cycling remainder, agent_retained, both conservation invariants hold exactly), late_funding_penalty (15 bps/day), consent_tally + default_vote_tally (exit-adjusted bases), default_interest_re_rate (declare/cure/waive-retroactive/accelerate), buyback_price (standard vs SERVICING_BREACH +500bps penalty), principal_reduction_allocation (oldest-first), committed_recompute.

**Smoke-test result** (final boot via `bash start.sh`, fresh store): `GET /api/facilities` → `200 {"meta":{"api_request_id":"req_4382...","api_request_timestamp":"2026-08-01T00:00:00.000Z","limit":10,"offset":0,"total_count":0,"has_more":false},"response_type":"array","data":[]}`; `POST /api/borrowers` → `201` with `data` containing `id`, `created_at`/`updated_at` `2026-08-01T00:00:00.000Z`, `version: 1`, `status: "ACTIVE"`. Hand-verified numeric scenarios: waterfall fee 2083/interest 25000/principal 972917 with 60/40 split and remainder cent to the larger share; 30/360 clamp (10-01→10-31 = 29 days → 9666); three-segment cure re-rate (3333+5000=8333); retroactive waive (13150 = never-defaulted value); rate-change segmentation (18000+1333=19333); clawback reversal restoring exact pre-payment ledgers (2000000/0, participant cumulatives 0/0, draw as_of rolled back); closure bubbles and reopening; transfer conservation; buyback penalty pricing (75833 = floor(1516667·5%)); tally adjusted base after exit (5000→10000); all 38 error codes exercised across 13 scenario scripts.

**PRD-interpretation decisions** (where prose admitted latitude):
1. **Draws only from COMMITTED** (§3.3 "any other status rejects with ERR_FACILITY_NOT_COMMITTED"), with the §3.7 carve-out that ACCELERATED rejects with ERR_INVALID_STATE_TRANSITION; IN_DEFAULT draws get ERR_FACILITY_NOT_COMMITTED (the error catalog lists ERR_FACILITY_IN_DEFAULT as blocking only solicitation/transfers/prepayments).
2. **Facility bubble cascade within one recompute**: a single commit that fills the ceiling lifts STRUCTURING→SYNDICATING→COMMITTED in one call (otherwise single-participant deals could never draw).
3. **Accrual engine**: per-draw append-only accrual ledger (each materialization floors per segment using the outstanding *at that materialization*); waive replays the ledger with the waived case's window removed (preserving prospective rate-change history); remitted-payment reversal restores ledgers exactly via per-draw snapshot (ledger length + prior as_of) stored on the run.
4. **Rate changes** record (effective_date, rate) history effective from the current clock date at implement; accrued history is never restated.
5. **Tally adjusted bases**: exit records store a base reduction (full commitment on buyback exit, 0 on full-transfer exit since the transferee absorbs it); exits count when `exit_time >= voting_open_at`/`declared_at`; participant exit recomputes tallies of *all* live solicitations/cases on the facility, not only ones the exiter voted on.
6. **Clock endpoint** echoes the exact `to_iso8601` input string as `current_utc`; resource/meta timestamps format the logical clock with 3 fractional digits (§2.5); meta timestamps also use the logical clock for determinism.
7. **Version starts at 1** at creation; each API-call mutation bumps each affected entity once (per-request touch guard), including share/aggregate recomputation targets.
8. **Settlement due allocation remainder** uses the waterfall's pinned order (share DESC, commitment DESC, created_at ASC, name ASC) — PRD pins the sum-exact requirement but not the settlement remainder order.
9. **Ownership vs existence**: path ids resolve first (404) before ownership (403) since ownership needs the loaded resource; ownership before body-reference checks.
10. **Vote on non-SOLICITING solicitation** → ERR_VOTING_CLOSED (error-catalog condition) rather than ERR_INVALID_STATE_TRANSITION (the priority-6 parenthetical); non-FUNDED/nonexistent voter identity → ERR_PARTICIPANT_NOT_ELIGIBLE (409, eligibility), likewise nonexistent transferor/demander → eligibility errors rather than 404.
11. **Pagination** clamps out-of-range limit to [1,100] and offset to ≥0 (PRD specifies min/max but not the failure mode); lists sort created_at ASC with insertion-sequence (not id) as the stable tiebreak — "ties never fall back to ids".
12. **BORROWER_SUBSTITUTION's new_borrower_id** existence is checked at implement (per the state-machine side effect), not at create.
13. **Servicing fee days** clamped at 0 if value_date precedes the baseline (negative fees would violate the waterfall invariants).
14. **Solicitation buffer** compares only against currently-SOLICITING windows; exactly-24h separation is permitted ("within 24h" read as strictly less).

Orchestrator note: Steps 5 and 6 ran concurrently in a single message (physical isolation — impl-gen started before test_suite/ existed). Known tension point handed to Step 7: Step 5 fixtures create follow-on draws while the facility is FUNDING/ACTIVE (design-recipe semantics), while Step 6 decision #1 allows draws only from COMMITTED. Step 7's PRD-first protocol will adjudicate.

## Step 7: Run Tests and Iterate — 2026-08-15T01:45:00.000Z

All 8 rounds pass: 98/98 in every round. The sweep is clean — exiting with the summary.

## Summary

**Iterations run:** 2 (sweep 1: same 7 failures in all 8 rounds, zero flakiness; sweep 2: 98/98 × 8 rounds clean).

**Tests deleted (2):**
1. `test_02_draws_and_funding.py::TestDrawWindowOverlap::test_draw_windows_half_open_adjacency_allowed` — unique-derivability collapse. Both asserted outcomes (201 for an adjacent second draw; `ERR_DRAW_WINDOW_OVERLAP` for a straddling third) require two live non-cancelled draws on one facility, but PRD §3.3 verbatim ("a facility whose status is `COMMITTED` — any other status rejects with `ERR_FACILITY_NOT_COMMITTED`") plus the first-draw bubble to FUNDING makes a second live draw uncreatable; the PRD-faithful reference implementation fails the test. Scaffold rule: `Difficulty/resource_temporal_overlap/draw_windows_half_open_adjacency_allowed` (design recipe assumed draws are allowed in FUNDING/ACTIVE). The reachable kernel (cancelled windows are freed) stays covered by `test_cancelled_draw_window_is_freed`.
2. `test_04_distribution_lifecycle.py::TestWaterfallEdgeScenarios::test_principal_allocation_oldest_draw_first` — same collapse: the oldest-first principal walk across multiple settled draws requires creating a second draw, which §3.3 forbids; setup itself is unconstructible under PRD. Scaffold rule: `Corner/calculations/principal_allocation_oldest_draw_first`.

**Fixes to `test_suite/` (5):**
1. `test_02::test_draw_headroom_exact_equality_boundary` — restructured to the PRD-reachable boundary: a single draw equal to the ceiling succeeds (facility lands FUNDING); a single draw one cent over the ceiling on a fresh COMMITTED facility rejects with `ERR_DRAW_EXCEEDS_COMMITMENT` (§3.3 verbatim).
2. `test_02::test_draw_full_headroom_single_shot_and_zero_amount_rejected` — the follow-on draw on the FUNDING facility now asserts `ERR_FACILITY_NOT_COMMITTED` instead of `ERR_DRAW_EXCEEDS_COMMITMENT` (§3.3 verbatim; §2.9 puts facility posture at priority 7, ahead of the headroom cap at 13).
3. `test_05::test_waterfall_conservation_and_reversal_compensation` — removed the post-reversal `accrued_interest_cents == 50_000` assertion: §3.5's "restores … to their pre-payment values" does not uniquely determine the stored accrued figure (literal pre-payment stored value is 0, since §3.4 materializes accrual only at run creation — after the payment exists; the 50,000 reading requires "pre-payment" to mean "pre-remit"). Replaced with the verbatim §2.7 standing invariant: facility `accrued_interest_cents` equals the sum of `accrued_unpaid_interest_cents` over settled draws. All other reversal assertions (clawback statuses, principal restore to 5,000,000, cumulative ledgers zeroed) kept.
4. `test_07::test_default_declare_with_active_case_rejected` — expectation changed from `ERR_DEFAULT_ALREADY_ACTIVE` to `ERR_INVALID_STATE_TRANSITION` (§3.7 verbatim: "Declaration requires the facility to be `ACTIVE` — otherwise `ERR_INVALID_STATE_TRANSITION`"; §2.9 pins target-state legality at priority 6 before the single-active-default rule at 9, and a DECLARED case holds its facility IN_DEFAULT per the hop-1 cascade).
5. `test_11::test_occ_draw_create_stale_version_rejected` — staleness now expressed as `expected_facility_version = current − 1` on the still-COMMITTED facility (§2.8: any mismatch rejects with `ERR_STALE_VERSION`), instead of bumping the version via a real first draw, which flips the facility to FUNDING and trips priority 7 (`ERR_FACILITY_NOT_COMMITTED`) before the OCC check. A positive control (current version accepted, 201) retained.

**Fixes to `test_helpers/`:** none — fixtures construct PRD-consistent preconditions; every failure traced to test-suite assertions, not fixture behavior.

**Fixes to `implementation/`:** none — the implementation was PRD-faithful on all 7 failures. The known tension resolved in favor of the implementation: PRD §3.3's "any other status rejects with `ERR_FACILITY_NOT_COMMITTED`" is verbatim and unambiguous under the two-reader test, so the design-recipe multi-draw semantics encoded in the tests lost.

## Step 8: Finalize PRD — 2026-08-15T02:00:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1893_loan_participation_syndication/workspace/PRD_FINALIZED.md` written — exactly one in-place revision; everything else in the Step 7 diff traced to PRD prose that was already verbatim-correct.

## Line counts / delta

- `PRD.md`: 375 lines; `PRD_FINALIZED.md`: 375 lines (0.0% line delta — one paragraph revised inline at line 197, no sections added or removed).

## Changes (1)

- **§3.5 (Borrower Payments, the Distribution Waterfall, and Reversal) — revise** — replaced the closing universal "After a remitted-payment reversal, the facility ledgers equal their pre-payment values exactly." with a pinned mechanism plus a qualified claim: the reversal "unwinds the reversed run's own accrual materialization: each draw the remittance touched returns its `accrual_as_of_date` and stored accrued interest to the values held immediately before that run was created — not the materialized-to-`value_date` figures the run computed at creation (§3.4) — and the facility's `accrued_interest_cents` is recomputed as the sum over its settled draws"; the pre-payment-equality claim is kept but scoped to the canonical flow (remittance touched every settled draw, no interleaved materialization). — `implementation/routes_payments.py:115-154` (reversal rollback via `_remit_effects` + `_accrual_snapshot`), snapshot taken at `implementation/routes_payments.py:196-203`, recomputation via `implementation/calc.py:193-202`.

## Pre-edit search log (mandatory enumeration for the single edit)

**(a) Subject:** what "restores … to their pre-payment values" concretely means for accrued interest on a remitted-payment reversal — literal pre-payment stored figure (0 in the canonical scenario) vs. the run's materialized-to-`value_date` figure (50,000). Impl restores the former, via a pre-run snapshot.

**(b) Impl paths enumerated and read:**
1. `routes_payments.py:93-159` `payment_reverse` — REMITTED branch rolls back only draws in `run._remit_effects` to `run._accrual_snapshot` (ledger truncated to snapshot length, `accrual_as_of_date` restored, `_net_distributed` debited), then recomputes facility accrued as the sum over settled draws; CLOSED → ACTIVE reopen. ALLOCATED branch (105-114) performs **no** accrual rollback — so the edit is scoped strictly to remitted reversals.
2. `routes_payments.py:196-203` `run_create` — the snapshot is captured *before* `materialize_facility(fac, value_date)`; under supersession each run snapshots at its own creation, so the restore target is "immediately before the (remitted) run was created," not "when the payment was recorded."
3. `routes_payments.py:294-342` `run_remit` + `calc.py:419-455` — only draws with a positive take appear in `_remit_effects`; a zero-pool remit (e.g., fee consumed the whole payment) touches no draw, so no accrual rollback occurs on reversal.
4. `calc.py:220-243` `materialize_draw`/`materialize_facility` and `calc.py:264-276` `prospective_accrued` — materialization happens at run creation, after the payment exists; consistent with §3.4's five-moment list.
5. `routes_defaults.py:34-58, 115` (declare/cure/waive/accelerate) and `routes_transfers.py:342-343` (buyback settle) — the other four materialization moments; any of them can intervene between payment recording and run creation, again forcing "before that run was created" wording.
6. `routes_funding.py:34-118` `draw_create` — facility must be COMMITTED and the first draw bubbles it to FUNDING, so at most one settled draw ever exists; "each draw the remittance touched" is exact regardless.
7. `domain.py:124-147` close/reopen helpers — untouched by the edit.

**(c) Wording adjustments made:** the naive draft ("returns to the values held when the payment was recorded" + keeping the unqualified "ledgers equal their pre-payment values exactly") was revised twice: first to "immediately before that run was created" (paths 2 and 5 — superseded runs' and default events' materializations persist in the snapshot), then the equality claim was qualified to the canonical flow (path 3 — a zero-take remit leaves the materialized accrual in place, so the universal claim would have been false).

## Step 7 items evaluated with no edit (PRD already verbatim-right)

- Deleted `test_draw_windows_half_open_adjacency_allowed` / `test_principal_allocation_oldest_draw_first` — §3.3's COMMITTED-only rule and §3.5's oldest-first walk already match impl (`routes_funding.py:56-57`, `calc.py:35-40, 419-434`); the multi-draw setups were unconstructible under both.
- §3.3 draw-window overlap sentence (candidate c) — impl implements it verbatim (`routes_funding.py:62-68`, half-open over non-cancelled siblings at priority 10); the sentence is a true conditional, merely unreachable with two live draws — no scoping needed.
- §3.4 materialization timing (candidate b) — the five-moment list is exhaustive and impl matches exactly (four `materialize_facility` callsites + run creation); payment recording never materializes (`routes_payments.py:38-73`).
- `test_02` headroom boundary / follow-on draw error — §3.3 "may not exceed" + §2.9 priority 7-before-13 match impl (`routes_funding.py:56-57, 70-74`).
- `test_07` default declare with active case — §3.7 verbatim + §2.9 priority 6-before-9 match impl (`routes_defaults.py:76-82`).
- `test_11` OCC stale draw version — §2.8 verbatim matches impl (`routes_funding.py:59-60`).

## Step 9: Complete PRD — 2026-08-15T02:10:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1893_loan_participation_syndication/workspace/PRD_COMPLETED.md` is written as a minimal patch over `PRD_FINALIZED.md`, pinning every place where the prose admitted multiple readings to the behavior `implementation/` actually exhibits.

**Size delta:** PRD_FINALIZED.md 375 lines / 72,144 chars → PRD_COMPLETED.md 377 lines / 76,559 chars (+2 lines, +4,415 chars, 28 hunks — all in-paragraph inserts/revisions, no new sections).

**Counts:** 26 ambiguity-pins, 2 mismatch-revisions.

**Changes (one per bullet):**

- §2.1 — insert — ambiguity — `System` or any unrecognized role string fails with `ERR_FORBIDDEN_FOR_ROLE` (403) on every endpoint — auth.py:8,24-37
- §2.2 — insert — ambiguity — undefined paths and unsupported methods on defined paths return `ERR_NOT_FOUND` (404) in the standard error envelope — app.py:41-42, responses.py:59-64
- §2.3 — revise — ambiguity — `limit`/`offset` out-of-range values clamp (1/100/0) rather than reject; non-integer values fail `ERR_INVALID_REQUEST`; `created_at` ties break by insertion order; `has_more` ≡ offset + returned < total_count — domain.py:26-46, responses.py:35-45
- §2.4 — insert — ambiguity — clock accepts offset-bearing datetimes or bare dates, stores/echoes the supplied string verbatim in `current_utc`, may move backward (no monotonicity check), and the envelope `api_request_timestamp` reads from the same logical clock — store.py:57-94, routes_core.py:24-35
- §2.5 — revise — ambiguity — `version` starts at 1 on creation; all touches of one resource within a single API call coalesce into exactly one version increment/`updated_at` refresh — store.py:120-146
- §2.9 — insert — ambiguity — priority-5 request shape explicitly includes "body is a well-formed JSON object" — auth.py:40-49
- §2.10 — insert — ambiguity — nested child lists (`/facilities/{id}/…`) accept only the `status` filter — routes_core.py:158-194
- §3.1 — insert — ambiguity — facility-creation validation is syntactic: `total_commitment_cents` strictly positive; the three bps fields allow zero; `currency` only non-empty (no ISO 4217 format check); governance-knob overrides take any integer — routes_core.py:81-117
- §3.2 — insert — ambiguity — participant registration has no facility-status guard; guards fire at commit/withdrawal — routes_core.py:201-224
- §3.2 — revise — ambiguity — a `PROPOSED` participant may be withdrawn in any facility status (the pre-funding guard applies only to `COMMITTED`) — routes_core.py:263-281
- §3.3 — insert — ambiguity — funding-settlement due-cent remainders use the same pinned order as the §3.5 waterfall (descending share, desc commitment, earlier created_at, asc name, cycling) — routes_funding.py:94-96, calc.py:303-330
- §3.3 — insert — ambiguity — a draw is born with `outstanding_cents` = 0 and `settled_at` = null — routes_funding.py:76-91
- §3.4 — revise — ambiguity — accrual windows also split at implemented rate-change effective dates; each segment accrues at the base rate in effect at its start — calc.py:141-190, routes_mods.py:268-273
- §3.5 — insert — ambiguity — servicing-fee baseline tie-break (earliest `settled_at`, then earlier `created_at`) and a `value_date` before the baseline counts zero fee days — calc.py:283-296
- §3.5 — revise — ambiguity — closure predicate is "a payment currently in `REMITTED` status" (a reversed payment no longer counts) — domain.py:124-147, routes_payments.py:336-341
- §3.6 — insert — ambiguity — `terms` value validation per type (non-negative int rate, positive int cents, parseable date, non-empty string) — routes_mods.py:90-104
- §3.6 — insert — ambiguity — the 24-hour solicitation buffer compares only against requests currently `SOLICITING`; a gap of exactly 24h passes — routes_mods.py:165-175
- §3.6 — insert — ambiguity — recast re-snapshots `voted_share_bps` from the participant's current share — routes_mods.py:346-351
- §3.6 — revise — **mismatch** — consent-tally adjusted base subtracts only commitments that left the facility: buyback exits subtract in full, full-transfer exits subtract nothing (transferee absorbed); zero base yields zero shares — calc.py:345-376, domain.py:85-106
- §3.7 — revise — ambiguity — `INSOLVENCY` moves the borrower to `INSOLVENT` from `ACTIVE` or `DELINQUENT` alike; non-insolvency moves only `ACTIVE` → `DELINQUENT` — routes_defaults.py:116-125
- §3.7 — revise — **mismatch** — default-tally adjusted base follows the same rule (buyback exits subtract, transfer exits don't; zero base → zero shares) — calc.py:379-401
- §3.7 — revise — ambiguity — cure's straight-to-`CLOSED` path uses the same currently-`REMITTED` predicate — routes_defaults.py:48-54, domain.py:131-139
- §3.9 — insert — ambiguity — a named transferee participant is not checked for facility membership or status; `transferee_name` always creates a new entrant at settle — routes_transfers.py:56-62, 189-207
- §3.9 — insert — ambiguity — settle-time re-validation also fails with `ERR_TRANSFER_EXCEEDS_COMMITMENT` when the transferor no longer holds `COMMITTED`/`FUNDED` — routes_transfers.py:179-181
- §3.9 — insert — ambiguity — a newly created transferee participant starts with `funded_cents`/cumulative ledgers at zero (share recomputed) — routes_transfers.py:194-207
- §3.9 — insert — ambiguity — the four buyback price fields stay null until settlement — routes_transfers.py:270-285
- §3.9 — insert — ambiguity — the buyback "settle date" is the current clock date at the settle call — routes_transfers.py:342-343
- §4 — insert — ambiguity — the modification-request `borrower_id` filter is an alias filtering on `requested_by_borrower_id` — routes_mods.py:138-148

Everything else walked (all 16 source files: endpoints, state machines, formulas, OCC rules, error catalogue, filters, envelope shapes, defaults, cascade hops) was already uniquely pinned by PRD_FINALIZED.md and left untouched.

Orchestrator final verification: workspace/PRD_COMPLETED.md exists (76,559 bytes); final sweep artifacts results.1–8.json all pass (8/8 rounds clean, 784/784 test-passes = 98 tests × 8 rounds). Pipeline complete.
