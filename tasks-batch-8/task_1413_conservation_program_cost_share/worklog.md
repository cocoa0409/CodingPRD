# Worklog — task_1413_conservation_program_cost_share

## Step 1: Create Task Directory — 2026-08-13T05:24:00.000Z

Task directory `tasks/task_1413_conservation_program_cost_share/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline dispatcher. Step 1 treated as DONE per invocation instructions; no index scan performed, no other task_* directory touched.

## Step 2: Generate Scaffold — 2026-08-13T06:37:00.000Z

All artifacts complete and verified. Final report:

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/SCAFFOLD.yaml` (102 KB) — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (94 KB) — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/SCAFFOLD_CORNER_DESIGN.yaml` (157 KB) — single top key `scaffold_corner_design`

## Inventory

| Element | Count |
|---|---|
| Entities (§1.1) | 14 |
| State machines (§1.2) | 11 entries, 59 transitions (incl. parallel payment_status dimension on ContractPracticeItem) |
| Concurrency rules (§1.2.1) | 3 (OCC on Contract.version ×2, ContractPracticeItem.version ×1) |
| Calculations (§1.3) | 12 |
| Validation rows (§1.4) | 11 priority tiers |
| Endpoints (§1.5) | 66 (incl. `POST /_clock/set_current_utc`, default 2026-08-01T00:00:00Z) |
| Errors (§1.6) | 73 |
| Roles (§1.7) | 5 (Applicant entity-backed; ProgramAdmin/ConservationPlanner/PaymentOfficer/QualityAssuranceOfficer opaque) |
| §1.8 instances | 19 (9 rules × ≥2; rule 2 has 3, one per mode a/b/c) |
| §1.9 instances | 56 (48 active + 8 `excluded_because` stubs), across all 9 guide sections |

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (1117 calls scanned, 0 violations.) A supplementary self-audit additionally confirmed: full `${var}` placeholder closure, instance-name uniqueness across both design files, every `grounds:` reference resolves, every error id referenced, enum-value closure for all machines, no forbidden race vocabulary.

## Notable design decisions

- **Archetype**: quota/allocation (funding pools with `allocated == available + obligated + paid` trichotomy) × compliance/audit, with `segregation_of_duties` role model (approver ≠ certifier, spot-checker ≠ certifier, confirmer ≠ reporter).
- **Difficulty rule coverage**: dual variants = provisional-vs-verified ranking score (Application) and scheduled-vs-certified payment (ContractPracticeItem); combinatorial modes = per-item-then-sum rounding (75006 vs 75005 on 2.5 ac × 15001¢), base-keyed tier bonus (base 55 → 60, not 70), min(qty×rate, documented-cost) cap; cascades = spot-check FAIL depth-3+ (request→item→obligation→demand) and DROP_PRACTICE depth-2; temporal overlap = closed-inclusive program windows vs half-open parcel×practice maintenance intervals; invariants = pool trichotomy and advance issue/return neutrality.
- **Shadow accounting at ranking**: the waterfall selection computes running shadow availability but mutates no pool fields — funds move only at contract obligation (pinned in the calculation and asserted in a corner instance).
- **Sweep freeze during modification review**: item-expiry sweep skips items whose contract is MODIFICATION_PENDING, which keeps `ERR_EXTENSION_WINDOW_CLOSED` reachable at approve time (corner instance `extension_boundary_ladder` exercises request-time length bounds, exact +365d approval, and approve-time window closure).
- **api_prefix `/eqip` with `{id}` path params** throughout so the lint's segment-derivation and sub-resource FK checks resolve; every FK has a reverse GET (sub-resource or filtered list).
- **All formula-derived assert literals pre-computed in Python** (scores 85/35/70/60/50, payments 324000/144000/270000, cap 27002, dates 2026-10-30, 2031-09-30, 2036-09-28, 2026-12-29T00:00:01Z, etc.).

## Step 3: Copy Shared Files — 2026-08-13T06:39:00.000Z

Copied `/home/ubuntu/github/CodingPRD/INSTRUCTION.md` to `tasks/task_1413_conservation_program_cost_share/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-13T07:02:00.000Z

PRD generation complete. Summary:

**Output:** `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/workspace/PRD.md` — 377 lines.

**Section coverage:**
- §1 Introduction (2 paragraphs: business context + role/segregation framing)
- §2.1–2.11: RBAC with per-role identity translation (4 opaque + `Applicant` entity-backed), the fixed §2.2 envelope block (verified byte-identical to `section-2.2-response-structure.md`), pagination (limit 10/1/100, offset 0, `created_at` ascending, meta fields, plus every list-endpoint filter parameter), common resource properties (incl. the explicit "rates and criteria carry only `id`/`created_at`, no `updated_at`/`version`" carve-out for the two `common_fields: false` entities), left-to-right nested-existence rules with all 12 NOT_FOUND IDs, an explicit 11-rung validation-priority ladder, the logical clock (startup default 2026-08-01T00:00:00Z, forward-only, full sweep battery), pool conservation invariant with forward/compensating pairs, integer-cents + round-half-up precision rules, all 3 OCC rules (`expected_contract_version` on modification approve/reject → `ERR_STALE_CONTRACT_VERSION` 412; `expected_item_version` on item PATCH → `ERR_STALE_ITEM_VERSION` 412; "no other endpoint takes a version field"), and the three segregation-of-duties boundaries.
- §3.1–3.8 (scattering zone, timeline-grouped): program config → registration/drafting/submission → screening/scoring/waterfall → contract drafting/obligation → installation/certification/lifespan → HU advances → payment requests/spot checks/revocation cascade → modifications/endings/recoupment. All 10 state machines, 12 calculations (incl. pinned evaluation orders, sum-of-rounded divergence note, shadow-availability waterfall, 4/5/6 modulus boundary, half-open obligation intervals), and every cascade hop (termination depth-3, spot-check failure depth-4) rendered in prose.
- §4: 66-row endpoint table, 4 columns only (Method/Path/Description/Roles); status-code paragraph (201 creation, 200 modification).
- §5: 73-row error table, 2 columns, statuses verified against the scaffold catalog.

**Zero-Silence self-audit (all mechanical, fence-aware):**
- Contract 1 field coverage: 96/96 required names present in backticks, 0 missing — PASS
- Contract 2 rule coverage: 11/11 validation priorities expressed as an ordered ladder; 3/3 OCC rules with endpoint + occ_field + error_id + 412; all state-machine transitions with preconditions paired to error IDs and side effects stated; 12/12 calculations fully expressed; 73/73 error IDs mentioned in §2/§3; endpoint side effects and applies_to scopes enumerated; sibling branches (PASS/FAIL, SCREENED_IN/OUT, approve/reject, confirm/dismiss, 3 recoupment sources, 3 modification kinds) given equal density — PASS
- Contract 3 §3 path purity: 526 backtick tokens scanned, 0 paths / 0 bare methods / 0 combos — PASS
- Cross-checks: §4 table exactly matches scaffold's 66 endpoints (no missing/extra); §5 table exactly matches 73 errors with correct HTTP statuses; all 66 enum/state values present verbatim; 5/5 role names present.

**Notable decisions:**
- The scaffold's terminate endpoint description mentions MODIFICATION_PENDING as a source state, but the state machine plus the explicit frozen-posture note and validation priority 5 reject termination during modification review; I rendered the state machine as canonical (terminate from DRAFT/OBLIGATED only) and kept the §4 description state-neutral.
- `advance_cap_pct` default 0.5 rendered as "one-half/half the scheduled amount" alongside the exact field name; modulus default 5 rendered as "requests 5, 10, 15 sampled; 4 and 6 not".
- Removed one clause ("no operation may drive any balance negative") that was not scaffold-backed, per the no-invention rule.
- Audit-extraction gotcha: the §2.2 verbatim JSON fences break naive backtick pairing; audits strip fenced blocks before tokenizing.

## Step 5: Generate Unit Tests — 2026-08-13T07:55:00.000Z

Generation complete. Summary:

## Files written

**`test_helpers/`** (under `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/test_helpers/`):
- `types.py` — 13 status enums, role enum, 15 entity TypedDicts; `PaymentScheduleRate`/`RankingCriterion` correctly omit `updated_at`/`version` (PRD §2.4 immutable config rows)
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per endpoint (48 methods incl. `set_clock`)
- `api_errors.py` — 73 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` — per-entity assertions, `assert_pool_invariants` (allocated == available+obligated+paid), `assert_advance_invariants`, `assert_instant_equal` (format-tolerant instant compare, since PRD pins instants but not sub-second serialization)
- `factories.py`, `constants.py`, `test_users.py` (staff shared constants + `make_applicant_headers(entity_id)` for the entity-backed Applicant role), `fixtures.py` (composable primitives + composite helpers: `setup_open_program`, `setup_screened_application`, `setup_obligated_contract`, `setup_certified_item`, `setup_disbursed_request`, `setup_hu_contract_with_advance`), `__init__.py` barrel

**`test_suite/`**: `conftest.py` + 9 test files (`test_01` program setup/windows … `test_09` security/envelope).

## Test counts
- **Total: 86 tests** — Queue A (Difficulty): **38** (19 instances × 2 each); Queue B (Corner): **48** (48 non-stub instances × 1 each). The 8 `excluded_because:` stubs in the errors section were not translated; all 8 `difficulty_instance` cross-references resolve to real queue-A instances.
- Automated audit confirmed: every instance covered to target, every tag resolves, every test docstring ends with exactly one verbatim `Design:` line, and every quoted PRD citation survives a whitespace-normalized literal containment check against `PRD.md`. Pytest collects 86; pyflakes clean.

## Instances skipped
None.

## Coverage-audit notes (deviations from design-yaml literals, all PRD-adjudicated)
1. **`pool_exact_fit_obligation_boundary`** — the yaml's `setup_api_calls` reuse the HU applicant for program B, which would price COVER_CROP at the HU rate (180000) and break the pinned exact-fit literal (150000). I introduced a separate non-HU applicant for program B so the pinned assertions (exact fit 150000==150000, 300 > 0 fails) hold as written.
2. **`obligation_overlap_half_open_adjacency`** — the yaml places the two applications on different parcels (P-300/P-301), but the PRD overlap rule keys on *same parcel + practice code*, so no overlap could ever fire. Both applications use parcel P-300; pinned asserts unchanged.
3. **Version absolutes** (`contract_modification_cycle_obligated_roundtrip`, `occ_modification_approve_stale_rejected`) — PRD §2.4 pins "increments by one on every mutation" but never the initial value, so tests assert relative +1 ratchets (`v_pending == v_obligated + 1`, etc.) instead of the yaml's absolute 3/4/6/7.
4. **`program_create_client_id_input_ignored`** — asserts the returned `id` is a server-minted UUID differing from the supplied one and `version != 99` (client value ignored); asserting `version == 1` would exceed what PRD uniquely derives (start value unstated).
5. The adjacency half of the obligation-overlap instance is partially confounded: at the adjacent certification instant the first obligation is already `SATISFIED` via the sweep (clock ≥ end_date), so that leg passes under both half-open and closed readings. The primary leg (overlap rejected while the prior obligation is ACTIVE with `end_date` past the new instant) fully discriminates.

## Step 6: Generate Implementation — 2026-08-13T07:55:00.000Z

Implementation complete and verified. Summary:

## Files written (all under `tasks/task_1413_conservation_program_cost_share/workspace/implementation/`)

- `start.sh` — executable launcher; guards `pip install` behind `python3 -c "import flask"`, then `exec python3 app.py`
- `requirements.txt` — flask only
- `app.py` — Flask app, blueprint registration, `ApiError`/404/405/500 envelope handlers, global request lock, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))`
- `db.py` — in-memory `STORE` (14 entity dicts keyed by id), logical clock starting at exactly `2026-08-01T00:00:00Z`, global creation counter; **no seeding of any kind**
- `errors.py`, `response.py`, `middleware.py`, `helpers.py`, `util.py`, `serializers.py`
- `services/calc.py`, `services/ledger.py`, `services/sweep.py`
- `routes/`: `programs.py`, `applicants.py`, `applications.py`, `contracts.py`, `practice_items.py`, `payment_requests.py`, `advances.py`, `modifications.py`, `spot_checks.py`, `obligations.py`, `demands.py`, `clock.py`

## Endpoints: 66/66 implemented

All 65 `/eqip/...` routes from the §4 table plus `POST /_clock/set_current_utc`.

## State machines: 10 implemented

ConservationProgram (SETUP→OPEN→CLOSED incl. sweep auto-close), Application (9 states incl. withdraw branches), Contract (DRAFT→OBLIGATED↔MODIFICATION_PENDING→COMPLETED/TERMINATED with full cascades), ContractPracticeItem certification dimension (7 states incl. retry cycle, expiry freeze under MODIFICATION_PENDING), item payment dimension (UNPAID→ADVANCE_HELD→PAID→RECOUPMENT_PENDING→RECOUPED), PaymentRequest (incl. DISBURSED→REVOKED 4-hop cascade), AdvancePayment (ISSUED→RETURN_DUE→ESCALATED→CLOSED), ContractModification, SpotCheck, MaintenanceObligation (incl. half-open overlap and SATISFIED sweep), RecoupmentDemand.

## Calculation modules (services/calc.py)

ranking_score (base → tier bonus keyed on base only → +bonus → cap 100 → ROUND_HALF_UP 2dp; provisional and verified variants), estimated_obligation (per-line round-half-up then sum), scheduled_amount (HU-conditional rate snapshot frozen at creation), certified_payment (min of rated amount vs documented cost, then advance offset), advance_cap (round-half-up of pct×scheduled, exact-cap allowed), pool_available + conservation invariant, ranking waterfall (score DESC → estimated ASC → created ASC tiebreak; HU-pool-first; shadow availability per run; selection mutates no pool balances), spot-check sampling (per-program sequence modulus), advance outstanding invariant, maintenance window (half-open `[start, end)`; SATISFIED at exactly end_date), recoupment amounts pinned per source.

## Validation / error handling

Single `ApiError(error_id, http_status)` type rendered into the exact scaffold envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data.error_id`/`message`). Checks ordered per the §2.6 ladder: headers (400) → role (403) → existence left-to-right (404 family) → applicant ownership (403) → state (409) → segregation (403) → sampled spot-check gate (409) → shape/uniqueness/cardinality (400/422/409) → temporal (409/422) → referential (422/409) → fiscal (402/422). Where PRD §3.6/§3.8 enumerate endpoint-specific gate orders citing the ladder (advance issuance, contract completion), the PRD's explicit enumeration is implemented. OCC: `expected_contract_version` → `ERR_STALE_CONTRACT_VERSION` (412) on modification approve/reject; `expected_item_version` → `ERR_STALE_ITEM_VERSION` (412) on item PATCH. All money is integer cents via `Decimal`+`ROUND_HALF_UP`; timestamps are logical-clock ISO-8601 with 3 fractional digits; list endpoints paginate with `limit`(default 10, 1–100)/`offset`(default 0) + `total_count`/`has_more` in `meta`, sorted `created_at` ASC with a creation-sequence tiebreak.

## start.sh contract — confirmed live

`bash start.sh` from `implementation/`: honors `$PORT` (verified on 18221), binds `0.0.0.0` (verified via `ss`), runs in the foreground via `exec`, boots with an empty store (`total_count: 0`), and responds within ~2s. Install is guarded so per-test reboots skip pip.

## Verification

Three smoke suites (run against fresh `start.sh` boots each) covering the full lifecycle passed: program config/window-overlap/ranking waterfall with shadow allocation and exact-fit, scoring math, contract drafting/obligation, HU advance (cap, offset, return, 90-day RETURN_DUE → +30d ESCALATED → demand → pay-close), certification + maintenance obligation (2-year lifespan math), payment pipeline with segregation-of-duties, sampled-request gate (modulus boundary: seq 4 no, 5 yes), FAIL-on-DISBURSED 4-hop revocation cascade, modification EXTEND/ADD/DROP with OCC staleness and approve-time `ERR_EXTENSION_WINDOW_CLOSED` (expiry sweep correctly frozen under MODIFICATION_PENDING), termination cascade, completion guards, pagination/filters, and pool conservation-invariant checks at every money movement.

One spec-interpretation note: the release formula "scheduled less advance net outstanding" is implemented as `scheduled − issued_cents` (the amount netted out of obligated at issuance) so the pool conservation invariant holds even after partial applicant returns; with no returns the two readings coincide.

## Step 7: Run Tests and Iterate — 2026-08-13T08:05:00.000Z

## Summary

**Iterations run**: 2 (initial sweep + 1 fix-and-rerun cycle).

**Tests deleted**: None.

**Fixes applied to `test_helpers/`**: None.

**Fixes applied to `implementation/`**:
- `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/workspace/implementation/routes/advances.py` (`return_advance` handler): Two changes to honor PRD §114 verbatim ("Advance issuance moves funds from obligated to paid; advance return moves them back") combined with PRD §3.6 ("reducing `paid_cents` by the returned amount") and PRD §3.8 ("any residual obligation still held for the contract is released back to the pool" at completion):
  1. Added `pool["obligated_cents"] += amount` alongside the existing `pool["paid_cents"] -= amount` — the return must move funds back to obligated, not just decrement paid.
  2. Added `item["_held_cents"] += amount` so the returned funds are tracked as residual obligation held for the contract; without this, `complete_contract` (which releases residual `_held_cents` back to available) would leave the returned balance stuck in `obligated_cents`, breaking `test_complete_succeeds_after_advance_return`.

**Notes**:
- The initial sweep also showed a consistent `test_scheduled_estimate_uses_planned_quantity_and_hu_snapshot` "server could not be restarted" error (15s plugin timeout under 8×CPU contention). This disappeared once the advance-return bug was fixed and did not resurface in the final sweep — a timing flake, not a test/implementation bug.
- Final state: 8/8 rounds × 86/86 tests passing.

## Step 8: Finalize PRD — 2026-08-13T08:17:00.000Z

Both edits are in place. The diff is exactly two sentences revised inline, no new sections. Here is the exit summary.

## Summary

**Line counts / %-delta**: PRD.md 377 lines → PRD_FINALIZED.md 377 lines; 0% line-count delta (2 sentences revised inline, nothing added or removed structurally).

### Changes (one bullet per edit)

- **§3.6 (advance return, line 192)** — revise — the full-return sentence previously pinned only "reducing `paid_cents` by the returned amount"; it now states the return moves the amount from paid back to obligated (`paid_cents` falls, `obligated_cents` rises) and that the returned amount is held once more as pool obligation for the item, released later on the same terms as any other remaining obligation — `implementation/routes/advances.py:59-60` (`pool["paid_cents"] -= amount`, `pool["obligated_cents"] += amount`) and `implementation/routes/advances.py:67` (`item["_held_cents"] += amount`).
- **§3.7 (disbursement pool effect, line 206)** — revise — the obligated-release formula changed from "less the advance amount already issued against the item" to "less the advance net outstanding on the item", matching the identical formula already used in §3.5 and §3.8 — `implementation/routes/payment_requests.py:178-181` (disburse releases `_held_cents`, which a prior full return has restored to the full scheduled amount, per `implementation/routes/advances.py:67`).

No PRD edit was needed for §2.8/§3.8: §2.8 ("advance return moves them back") and §3.8 ("any residual obligation still held for the contract is released back to the pool" at completion) already pinned the behavior and are kept verbatim.

### Per-edit pre-edit search log

**Edit 1 (§3.6 return sentence)**
- (a) Subject: pool-balance effects of a voluntary advance return (`POST /eqip/advance-payments/{id}/return`) and the downstream lifecycle of the returned funds.
- (b) Paths enumerated and read: `routes/advances.py:35-69` (the Step 7 site); `routes/contracts.py:279-346` `issue_advance` (forward leg: obligated→paid, `_held_cents -= issued`); `routes/demands.py:38-91` `pay_demand` (escalated-advance repayment: paid-only, no obligated leg — distinct endpoint, described by the separate §3.6/§3.8 sentences left untouched); `routes/payment_requests.py:143-205` `disburse_request` (releases `_held_cents` from obligated); `services/ledger.py:34-76` `release_item_obligation`/`cancel_item`/`expire_item` and callers `routes/modifications.py:122` (drop), `routes/contracts.py:203` (termination), `services/sweep.py:35` (expiry); `routes/contracts.py:228-274` `complete_contract` (releases residual `sum(_held_cents)`); `routes/contracts.py:54` + `routes/practice_items.py:74` + `routes/contracts.py:173` (held initialization/draft-edit/obligation); `services/sweep.py:39-52` (escalation moves no pool funds). Test evidence read: `test_06_advances.py::test_advance_full_return_restores_pool` (asserts obligated back to 360000 after return) and `test_complete_succeeds_after_advance_return` (asserts obligated 0 after completion of a post-disbursement residual return).
- (c) Wording adjustment: scoped the new clause to "a full return" (the return endpoint) so it does not leak onto the escalated-advance demand-payment path (`demands.py:60`), which legitimately reduces paid only; used the PRD's own defined phrase "remaining pool obligation" with explicit cross-references (§3.5, §3.7, §3.8) so every enumerated release path (disburse, cancel, expire, drop, completion) is covered without asserting any single one always applies.

**Edit 2 (§3.7 disbursement formula)**
- (a) Subject: the amount by which pool `obligated_cents` falls at disbursement.
- (b) Paths enumerated and read: `routes/payment_requests.py:175-183` (releases `item["_held_cents"]` verbatim); full `_held_cents` evolution grep — `routes/contracts.py:54` (set to `scheduled_amount_cents` at creation), `routes/practice_items.py:74` (draft edit delta), `routes/contracts.py:328` (issuance subtracts issued), `routes/advances.py:67` (return adds the amount back); confirmed at most one disbursement per item (§3.7 active-request gate includes `DISBURSED`, mirrored in `payment_requests.py`), so at disbursement `_held_cents` always equals `scheduled − advance net outstanding` (no advance: S; advance open: S − issued; advance fully returned: S − 0 = S). Verified §3.5 and §3.8 already phrase the parallel cancel/expire/drop releases as "scheduled less the advance net outstanding"; only §3.7 said "already issued", which mis-describes the return-then-certify-then-disburse case created by Step 7 fix 2 (impl releases the full scheduled amount there, not scheduled-minus-issued). No test covers disburse-after-return (`test_contract_complete_happy_path` exercises a no-advance disburse where both phrasings coincide), so implementation is the alignment target.
- (c) Wording adjustment: adopted the exact pre-existing §3.5/§3.8 phrase "the advance net outstanding on the item" rather than inventing new wording, keeping the three release formulas identical across sections; the following clause ("because the full scheduled obligation is released…") was checked and remains consistent under the new phrase in all enumerated cases.

## Step 9: Complete PRD — 2026-08-13T08:33:00.000Z

PRD_COMPLETED.md is written at `/home/ubuntu/github/CodingPRD/tasks/task_1413_conservation_program_cost_share/workspace/PRD_COMPLETED.md`.

**Source vs output**: `PRD_FINALIZED.md` (existed; used as source) 377 lines / 63,552 chars → `PRD_COMPLETED.md` 378 lines / 67,957 chars. Delta: +1 line (one catalogue row), +4,405 chars. No sections added; all changes are in-paragraph inserts/revisions plus one error-table row.

**Counts**: 36 ambiguity-pins, 2 mismatch-revisions (38 edits total).

**Change log** (PRD section — insert|revise — ambiguity|mismatch — what changed — impl evidence):

- §2.1 — insert — ambiguity — ownership checks on modification-request and demand-pay run against the parent contract's `applicant_id` — routes/modifications.py:364 (via contracts.py), routes/demands.py:42-43
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` rejected `ERR_INVALID_REQUEST` 400 — helpers.py:126-138
- §2.4 — revise — ambiguity — `version` starts at 1 on creation — helpers.py:181
- §2.5 — insert — ambiguity — body FKs resolved in field order; mismatched pairs yield 404 of the mismatched resource (`ERR_PRACTICE_ITEM_NOT_FOUND` / `ERR_PAYMENT_REQUEST_NOT_FOUND`) — routes/payment_requests.py:30-34, routes/spot_checks.py:26-39, routes/contracts.py:286-290,380-384
- §2.6 — insert — ambiguity — generic field/enum/bounds failures default to `ERR_INVALID_REQUEST` 400 — helpers.py:21-64
- §2.7 — insert — ambiguity — envelope `api_request_timestamp` and entity timestamps render from the logical clock — response.py:13, helpers.py:173,178-180
- §2.9 — insert — ambiguity — `standard_rate_cents`/`hu_rate_cents` must be integers; `advance_cap_pct` may be fractional — routes/programs.py:190-191 vs 46-47
- §2.11 — insert — ambiguity — null recorded counterpart (e.g. unset `certified_by_user_id`) cannot match; segregation check passes — routes/payment_requests.py:120-121, routes/spot_checks.py:86-87
- §3.1 — revise — mismatch — dropped "two-letter" qualifier on `state_code` (impl validates only non-empty string) — routes/programs.py:37, helpers.py:27-30
- §3.1 — insert — ambiguity — `window_end` before `window_start` rejected 400 — routes/programs.py:40-41
- §3.1 — insert — ambiguity — `spot_check_modulus` must be an integer ≥ 1 — routes/programs.py:42-45
- §3.1 — insert — ambiguity — open from non-SETUP → `ERR_PROGRAM_NOT_IN_SETUP`; close from non-OPEN → `ERR_PROGRAM_NOT_OPEN` — routes/programs.py:99-100,118-119
- §3.2 — insert — ambiguity — each `planned_practices` quantity must be a number > 0; `self_reported_answers` optional, defaults empty — routes/applications.py:61-72
- §3.2 — insert — ambiguity — submit from non-DRAFT fails `ERR_APPLICATION_NOT_DRAFT` 409 — routes/applications.py:117-118
- §3.3 — insert — ambiguity — `verified_answers` validated/clamped under the same rules as self-reported answers — routes/applications.py:168-169 (via `_clamp_answers`)
- §3.3 — insert — ambiguity — waterfall ties after `created_at` fall back to creation order — services/calc.py:114-119
- §3.3 — insert — ambiguity — among same-type pools, earliest-created fitting pool wins — services/calc.py:121,137-144
- §3.4 — insert — ambiguity — one-contract-per-application enforced solely by the `SELECTED` gate (no separate existence check) — routes/contracts.py:70-74,87
- §3.4 — insert — ambiguity — pool `version` increments on obligation — routes/contracts.py:173-174
- §3.5 — insert — ambiguity — certify/fail-certification check item state first, then require contract `OBLIGATED` (`ERR_CONTRACT_NOT_PAYABLE`) — routes/practice_items.py:110-116,167-173
- §3.5 — insert — ambiguity — obligation-overlap parcel is the one on the item's source application — routes/practice_items.py:130-132
- §3.5 — insert — ambiguity — DRAFT-contract items expire with no pool movement — services/sweep.py:33-35
- §3.6 — revise — ambiguity — `issued_cents` must be an integer ≥ 1 — routes/contracts.py:313-316
- §3.6 — insert — ambiguity — item `version` increments at advance issuance — routes/contracts.py:328-330
- §3.6 — insert — ambiguity — pool and item `version` increment on advance return — routes/advances.py:58-68
- §3.6 — insert — ambiguity — advance-sourced recoupment reduces `paid_cents` without touching `obligated_cents` (issuance never reversed) — routes/demands.py:58-61
- §3.7 — insert — ambiguity — missing/non-integer/sub-1-cent `documented_cost_cents` → `ERR_INVALID_REQUEST` 400 — routes/payment_requests.py:43-46
- §3.7 — insert — ambiguity — pool `version` increments on every successful disbursement — routes/payment_requests.py:183
- §3.7 — revise — mismatch — on disbursement offset, a zeroed advance closes from any state; an `ESCALATED` advance with residual outstanding stays `ESCALATED` (PRD said it moves to `RETURN_DUE`) — routes/payment_requests.py:185-196
- §3.7 — insert — ambiguity — spot-check `payment_request_id` belonging to another item → `ERR_PAYMENT_REQUEST_NOT_FOUND` 404 — routes/spot_checks.py:35-39
- §3.7 — revise — ambiguity — record-result gate order pinned: PENDING → inspector match → certifier segregation — routes/spot_checks.py:78-91
- §3.8 — insert — ambiguity — ADD_PRACTICE approval requires a program rate for the new code (`ERR_RATE_NOT_FOUND` 422) — routes/modifications.py:99-104
- §3.8 — insert — ambiguity — DROP_PRACTICE approval leaves an already-terminal item untouched — routes/modifications.py:121-122
- §3.8 — insert — ambiguity — termination from `MODIFICATION_PENDING`/`COMPLETED`/`TERMINATED` → `ERR_CONTRACT_NOT_OBLIGATED` 409 — routes/contracts.py:188-192
- §3.8 — insert — ambiguity — confirm-violation drops payment dimension only when `PAID` — routes/obligations.py:70-72
- §3.8 — insert — ambiguity — demand payment moves item to `RECOUPED` only when currently `RECOUPMENT_PENDING` — routes/demands.py:86-90
- §4 — insert — ambiguity — run-ranking returns 200 with `{ranked_count, selected_count, not_selected_count}` summary object — routes/programs.py:133-134, services/calc.py:158-162
- §5 — insert — ambiguity — added catalogue row `ERR_APPLICATION_NOT_DRAFT` | 409 Conflict (only impl error missing from PRD; verified by set-diff of all `ERR_*` IDs) — routes/applications.py:118

**Not pinned (deliberately skipped)**: unreachable fallbacks (missing rate row lifespan default in `certify`, missing-applicant handling in the waterfall), framework-level 404/405/500 handlers for unknown routes, and internal non-serialized fields (`_held_cents`, `_seq`). Everything else in the 12 route files, 3 services, and 5 core modules maps to PRD prose that was already unique or is now pinned.
