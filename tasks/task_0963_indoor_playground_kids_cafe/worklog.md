# Worklog — task_0963_indoor_playground_kids_cafe

## Step 1: Create Task Directory — 2026-08-10T02:17:32.725Z

Task directory pre-assigned by the invoking run: `tasks/task_0963_indoor_playground_kids_cafe/` with `workspace/` subdirectory already present. Step 1 auto-index scan skipped per invocation instructions. Recorded as done.

## Step 2: Generate Scaffold — 2026-08-10T02:43:39.342Z

Scaffold generation complete for `task_0963_indoor_playground_kids_cafe`. All three files are written and pass lint cleanly on the final run.

## Files produced

- `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

## Design summary (harder-than-expert calibration)

- **Complexity profile**: primary Temporal windowing, secondary Quota/allocation; layers = optimistic_concurrency, cascading_side_effects, rate_threshold_triggers, derived_field_reconciliation; flat topology; hierarchical_override role model; immediate consistency.
- **Entities: 15** — MembershipPlan, Guardian, Child, Waiver, SessionSlot, Visit, PartyRoom, PartyPackage, PartyBooking, CafeMenuItem, CafeOrder, LoyaltyTransaction (append-only, common_fields: false), StaffMember, SanitationTask, Incident.
- **State machines: 8** — incl. Visit with parallel dimensions (admission_status × payment_status), cyclic PartyBooking (CONFIRMED→RESCHEDULE_REQUESTED→CONFIRMED), cyclic Incident (RESOLVED→TRIAGED reopen loop), SessionSlot emergency-close cascade.
- **Concurrency rules: 3** (true OCC races per §1.2.1 filter): waiver-create-stale-guardian, slot-update-stale-version, party-booking-create-stale-room — all 412 ERR_STALE_VERSION with `expected_*_version` as `${var}` in every recipe.
- **Calculations: 7** — incl. dual-variant visit charge (block-provisional 2100 vs tiered-final 1650 for identical 90-min input), dual-variant membership credits (AVAILABLE_NOW 6 vs STATEMENT 7), mode-(a) party quote (pre-computed 37260/7452), mode-(b) per-line-then-sum cafe rounding (1378 vs 1377), mode-(c) post-redemption loyalty earn (8 not 13).
- **Validations: 28** ordered across auth/ownership/existence/state/safety/constraint/temporal/fiscal/referential priorities, enabling two distinct priority-conflict pairs (state-vs-safety, safety-vs-fiscal).
- **Endpoints: 74** — incl. logical clock (default 2026-05-01T00:00:00Z), ops-runs sweep, loyalty adjustments; every FK has a reverse-reachability GET.
- **Error catalog: 32 codes**, all triggerable and referenced.
- **RBAC: 6 roles** — Anonymous/Admin opaque; Guardian entity_backed:Guardian; FrontDesk/CafeStaff/Manager entity_backed:StaffMember with role-match + ACTIVE-status enforcement and Manager override.
- **§1.8 difficulty instances: 19** (9 rule_ids; combinatorial_formula carries 3 to cover modes a+b+c), all with structured setup_api_calls/trigger chains, pre-computed literal asserts, and replayed side-effect end-states.
- **§1.9 corner instances: 46** (38 active + 8 excluded_because stubs citing existing §1.8 instances) across 10 sections: entities, state_machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, validations_incidents (lost-child gates), consistency_model. Instance names unique across both files (65/65).

## Lint / validation results

- `scaffold_lint.py` verdict (final run, pasted verbatim):
  ```
  Coverage
    §1.5 endpoints declared:    74
    §1.1 entities declared:     15
    §1.8 instances scanned:     19
    §1.9 instances scanned:     38
    Calls scanned (§1.8+§1.9):  481
  VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
  ```
- Forbidden-vocabulary scan (simultaneously/first-writer-wins/race framing): clean after scrubbing two incidental uses.
- All numeric asserts (2100/1650/450, 6-vs-7 credits, 37260/7452, 1378/878, 8 points/108 balance, 31050, 3000 refund, 300 evacuation charge, quota floors 7/8/2, tier boundary 1000) were computed by hand-executing the pinned formulas and constants.

No sibling task directories were inspected at any point; the design was derived solely from the scenario text and the skill specification.

## Step 3: Copy Shared Files — 2026-08-10T02:44:02.762Z

Copied `./INSTRUCTION.md` to `tasks/task_0963_indoor_playground_kids_cafe/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-08-10T02:51:52.597Z

The PRD is generated and all three hard contracts pass. Summary:

## Generated artifact

`/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/workspace/PRD.md` — 325 lines, 7,060 words.

### Section structure

- **§1 Introduction** — 2 paragraphs (business pain points → system scope)
- **§2 Global Specifications** (9 subsections, domain-derived titles): 2.1 RBAC (headers, 6 roles, per-role `identity:` prose for `Guardian`/staff/`Anonymous`/`Admin`); 2.2 API Response Structure (emitted byte-verbatim from `section-2.2-response-structure.md`, including `req_RANDOMALPHANUM123456` and `"data": { }`); 2.3 Pagination (`limit` 10/1/100, `offset` 0, `created_at` ascending, meta fields); 2.4 The Logical Clock (startup default `2026-05-01T00:00:00Z`, `to_iso8601`/`current_utc`, never wall-clock); 2.5 Common Resource Properties (`id` UUID, `created_at`/`updated_at` ISO-8601 3-digit, `version` from 1; `LoyaltyTransaction` explicitly carries only `id`+`created_at`); 2.6 Money, Points, and Rounding (integer cents, round half-up per stage, floor for points); 2.7 OCC (all 3 rules with `expected_guardian_version`/`expected_session_slot_version`/`expected_party_room_version` → `ERR_STALE_VERSION` 412, stale-view framing only); 2.8 Validation Order (9-tier priority cascade auth → authorization → existence → state → safety → constraint → temporal → fiscal → payload); 2.9 Time Intervals, Capacity, and Quotas (half-open intervals, 70% quota, 30-min cleanup buffer)
- **§3 Business Logic** (9 subsections, process/lifecycle grouping): Guardians/Children/Waivers · Membership & Credits (AVAILABLE_NOW vs STATEMENT) · Slot day incl. resize cascade and 3-hop close cascade (+200 compensation) · Reservations & Walk-ins (provisional 1200/900-block quote, all gates) · Check-in/out & payment reconciliation (tiered 20/15/10 charge, evacuation half-charge, no-show, prepay) · Café (per-line rounding pin, redemption cap/balance order, allergen interlock) · Parties (quote/deposit formula, confirm, reschedule cycle, cancel waterfall 100/50/0, expiry, café cascade) · Staff/Sanitation/Incidents (lost-child check-out gate, reopen loop) · Loyalty & Ops Sweep (tier thresholds, earn order pin, 6 sweep output counts)
- **§4 Endpoint table** — all 74 endpoints, 4 columns only; **§5 Error catalogue** — all 32 errors, 2 columns only.

### Self-check results

- **Contract 1 (Field-Name Coverage): PASS** — entity fields 87/87, request-body identifiers 61/61, query params 8/8, path params 1/1, ops/clock output fields 7/7, all verbatim in backticks (verified programmatically; an initial false alarm was a checker bug from `§2.2` code fences shifting backtick pairing — fixed by stripping fences first).
- **Contract 2 (Rule Coverage): PASS** — 26 validation rules each paired with their exact `error_id` and status near the guarded workflow; 9-tier priority order stated explicitly; 3 OCC rules each name write operation + version field + `ERR_STALE_VERSION`/412 with no race/simultaneity framing; all 28 state transitions across 8 machines expressed with from/to states, preconditions, and side effects; all 7 calculations rendered as precise prose (constants embedded: 1200/900 blocks, 20/15/10 tiers, 10% member discount, 50% evacuation, 70% quota, 15% peak, 25% cap, 5000/20% deposit, 100/200/365-day/48h/7d/24h/10-min/15-min windows); cross-entity cascades (slot close 3-hop, party cancel → café → REVERSAL, waiver supersede) fully spelled out; sibling branches (refund waterfall, sock methods, credit vs prepaid settlements) symmetric.
- **Contract 3 (§3 Path Purity): PASS** — 516 backticked tokens in §3 scanned: 0 paths, 0 bare HTTP methods, 0 method+path combos.
- Additional checks: 54/54 enum/state values present, 32/32 error IDs present in §2/§3 prose, 74/74 §4 rows matching scaffold paths exactly, no fuzzy words ("approximately", "roughly", etc.), no pseudocode operators in prose, no OCC forbidden framing.

The two withheld files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) and all sibling task directories were not accessed.

## Step 5: Generate Unit Tests — 2026-08-10T03:12:05.786Z

Generation complete. Summary:

## Test counts

- **Queue A (Difficulty):** 36 tests covering 18 of 19 instances (≥2 each, as required)
- **Queue B (Corner):** 38 tests covering all 38 non-stub instances (≥1 each)
- **Total: 74 tests** across 11 files (`test_01_guardians_children_waivers.py` … `test_11_security_rbac.py`)
- Queue B `excluded_because:` stubs (8) were not translated; all their `difficulty_instance` cross-references resolve to real queue-A instances.

## Instances skipped

- **`Difficulty/compensating_invariant/loyalty_earn_and_reversal_invariant`** — the instance asserts `lifetime_points == 0` after a −8 manual `ADJUSTMENT` that compensates an 8-point earn. PRD §3.9 defines `lifetime_points` as accumulating "all points ever earned plus positive adjustments minus reversals, floored at zero" — a negative ADJUSTMENT-kind entry is neither a positive adjustment nor a REVERSAL, so a literal PRD reading yields `lifetime_points == 8`, not 0. The asserted outcome fails unique derivability (two faithful PRD-only readers disagree), so the instance was skipped rather than weakened. (Its sibling credit invariant and all other points-balance claims were covered elsewhere.)

## Helper infrastructure generated (`test_helpers/`, 9 files)

`types.py` (15 entity TypedDicts + 20 enums; `LoyaltyTransaction` correctly omits `updated_at`/`version` per PRD §2.5), `api_client.py` (78 endpoint methods on `GenericApiClient`), `api_errors.py` (32 error IDs + HTTP map registered via `set_error_http_status_map`), `assertions.py` (per-entity + credit-invariant checkers), `factories.py`, `constants.py` (all PRD thresholds), `test_users.py` (shared constants for opaque Anonymous/Admin only; per-instance `make_*_headers` builders for the entity-backed Guardian/FrontDesk/CafeStaff/Manager roles), `fixtures.py` (clock control, staff trio with role-matched headers, guardian+waiver+child chains, reserved/checked-in visit chains, party context/confirmed-booking helpers, cafe order + points seeding, OCC-fresh version reads), `__init__.py` barrel.

## Self-check results

- `python -m compileall` — clean
- `pytest --collect-only` — 74 tests collected, no import errors
- **Tag audit:** every test has exactly one `Design:` tag as the final docstring line; all 74 tags resolve to real instances; none point at stubs
- **Coverage audit:** 18/18 covered A-instances have ≥2 tests; 38/38 B-instances have ≥1 test
- **Verbatim-citation audit:** all 115 quoted spans in test docstrings grep-match PRD.md (whitespace-normalized); four initially-failing fused citations were split into contiguous sentence quotes and re-verified
- **Lint:** no `pytest.mark.skip`/`skipif`/`xfail`; no mention of "scaffold" anywhere in generated code

One design note: `checkin_state_beats_waiver_safety` was translated with two tests — the recipe-faithful one uses `validate_error_is_one_of([ERR_INVALID_STATE, ERR_SLOT_NOT_OPEN])` because the ops sweep auto-closes the slot, making both state-tier errors co-violated and the PRD silent on intra-tier order (the sanctioned `error-precedence` relaxation); a second test on an OPEN slot asserts `ERR_INVALID_STATE` exactly, pinning the state-tier-beats-safety-tier claim the instance exists to verify.

## Step 6: Generate Implementation — 2026-08-10T03:12:05.786Z

Implementation complete.

## Summary

**Files generated** (all under `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/workspace/implementation/`):
- `app.py` — single-file Flask app (~2,100 lines): 15-entity in-memory dict store (starts empty, no seeding), logical clock pinned at `2026-05-01T00:00:00Z` until advanced via `POST /_clock/set_current_utc`, response envelope per scaffold (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination fields `limit`/`offset`/`total_count`/`has_more` inside `meta`), full auth/RBAC middleware (`X-User-ID`/`X-User-Role`, staff role+ACTIVE matching, Guardian self-service ownership), Decimal-based round-half-up money math and floor-division points.
- `start.sh` — executable, guarded `pip install` (no-op once flask importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- `requirements.txt` — `flask>=2.0`.

**Endpoint coverage: 74/74** — every route in SCAFFOLD.yaml §1.5 / PRD §4 implemented, including all list sub-resources, the three OCC-guarded writes (`expected_guardian_version`, `expected_session_slot_version`, `expected_party_room_version` → `ERR_STALE_VERSION` 412), and both ops endpoints.

**Error catalog coverage: 32/32** — all error IDs in the catalog implemented with their exact HTTP statuses (incl. 402 for `ERR_INSUFFICIENT_CREDITS`/`ERR_INSUFFICIENT_POINTS`, 412 for OCC, 422 vs 409 distinctions).

**State machine coverage: 8/8** — SessionSlot (open/close with full 3-hop cascade: RESERVED→CANCELLED, CHECKED_IN→EVACUATED at 50% tiered charge, PREPAID→REFUNDED, credit restore, +200 ADJUSTMENT per affected guardian), Visit admission_status (incl. WALK_IN created directly CHECKED_IN) + parallel payment_status, PartyBooking (HELD→CONFIRMED→RESCHEDULE_REQUESTED→CONFIRMED cycle, deposit refund waterfall 100%/50%/0%, cafe-order cancel cascade with REVERSAL entries), CafeOrder, SanitationTask, Incident (cyclic RESOLVED→TRIAGED reopen re-engaging the lost-child gate), Waiver (create-with-supersede + ops expiry). Ops run emits all six counters.

**Boot-check results:** `bash start.sh` boots cleanly from a fresh process each time (verified 4 separate launches on distinct ports). Fresh store confirmed empty; ops-run on fresh boot returns all-zero counts. End-to-end smoke tests passed: waiver OCC supersede (412 on stale), slot overlap 409, slot-not-open 409, reservation quote 2100 for 90 min, check-in window gating, check-out final charge 1650 with refund_delta 450 (prepaid 2100), allergen conflict 422, per-line discount rounding, loyalty earn with tier multiplier, party quote with Saturday peak surcharge (37950) and deposit floor/20% rule (7590), room-version OCC 412, conflict detection with 30-min cleanup buffer, duplicate-visit 409, credit hold/available/statement semantics, cancel cutoff 422 for guardians but staff override, emergency close evacuation at 150 cents with 200-point compensation, and the lost-child check-out gate (409 → 422 resolve without reunion → checkout succeeds after resolve).

## Step 7: Run Tests and Iterate — 2026-08-10T03:23:24.118Z

All 8 parallel rounds pass 74/74 with zero failures and zero errors. Clean sweep achieved.

## Summary

- **Iterations run:** 2 sweeps (initial diagnostic sweep + 1 post-fix verification sweep, all 8 rounds green).

- **Tests deleted:** none. Every failing test traced to a verbatim PRD rule; all failures were test-artifact bugs, not PRD-silence or unique-derivability collapses.

- **Fixes applied to `test_helpers/`:** none.

- **Fixes applied to `test_suite/`:**
  - `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/test_suite/test_02_membership_credits.py` — `test_reserve_then_cancel_restores_credit_invariant`: the `setup_reserved_visit` fixture already books a RESERVED visit for `ctx["child"]` on the slot, so the test's own `create_visit` for the same child+slot correctly tripped `ERR_DUPLICATE_VISIT` (PRD §3.3: "no second visit may be created for the same child on the same slot while one already exists in RESERVED or CHECKED_IN"). Fixed by booking the credit-funded visit under test for a second child (same pattern as `_setup_one_held_one_consumed`).
  - `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/test_suite/test_05_checkin_checkout_charging.py` — `test_expired_waiver_blocks_checkin` and `test_cancelled_visit_checkin_on_open_slot_is_invalid_state`: both created the reservation against a SCHEDULED slot, which the implementation rightly rejects with `ERR_SLOT_NOT_OPEN` (PRD §3.3: "The target slot must be `OPEN`"). Fixed by opening the slot at setup via `create_open_slot` and removing the now-redundant later `open_session_slot` call.
  - `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/test_suite/test_09_party_bookings.py` — `test_sanitation_overdue_blocks_party_confirm`: the booking was created at clock 2026-06-01, then the clock jumped to 2026-06-03 and the ops sweep expired the HELD booking per PRD §3.7's 24-hour hold-expiry rule, so confirm returned `ERR_INVALID_STATE` instead of the intended `ERR_SANITATION_OVERDUE`. Fixed by creating the booking after advancing the clock (booking age 0 at sweep time; sanitation task still overdue).

- **Fixes applied to `implementation/`:** none — the implementation was PRD-faithful in every failure; all four persistent failures were test-setup violations of PRD preconditions.

- **Flakiness note:** the intermittent "API server could not be restarted" errors seen in rounds 1–7 of the first sweep (5 distinct tests, never an assertion failure) were load-induced boot contention under the 8-round parallel sweep; they did not recur in the verification sweep and required no code change.

## Step 8: Finalize PRD — 2026-08-10T03:25:19.607Z

Verification complete. All three Step 7 items map to verbatim PRD rules and the implementation matches them exactly, so no edits are warranted. `PRD_FINALIZED.md` is a byte-identical copy of `PRD.md`.

**Summary on exit**

- **Line counts:** PRD.md = 325 lines; PRD_FINALIZED.md = 325 lines; delta = 0 (0.0%). `diff` confirms byte-identical.

- **Changes made:** none (0 edits). This matches the expectation flagged in the method: all Step 7 items were test-side setup bugs against rules the PRD already stated verbatim, with zero implementation fixes and zero test deletions.

- **Per-diff-item verification (verbatim PRD coverage, no edit needed):**

  1. `test_02_membership_credits.py` / `test_reserve_then_cancel_restores_credit_invariant` (duplicate visit) — Covered verbatim by PRD §3.3, line 145: *"no second visit may be created for the same child on the same slot while one already exists in `RESERVED` or `CHECKED_IN` — a violation is `ERR_DUPLICATE_VISIT` (HTTP 409)."* Implementation: `/home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/workspace/implementation/app.py:1538-1541` enforces exactly this (same slot + same child + status in RESERVED/CHECKED_IN → 409). The failure was a fixture bug (the `setup_reserved_visit` fixture already booked `ctx["child"]` on the slot). No PRD silence.

  2. `test_05_checkin_checkout_charging.py` / `test_expired_waiver_blocks_checkin` and `test_cancelled_visit_checkin_on_open_slot_is_invalid_state` (slot not OPEN) — Covered verbatim by PRD §3.3 line 145 (*"The target slot must be `OPEN`"*), §3.2 line 137 (*"only `OPEN` slots admit new visits and check-ins, and any attempt against a slot in another state is rejected with `ERR_SLOT_NOT_OPEN` (HTTP 409)"*), and §3.4 line 157 (*"The slot must be `OPEN` (else `ERR_SLOT_NOT_OPEN`)"*). Implementation: `app.py:1507-1508` (visit creation) and `app.py:1633-1634` (check-in) enforce exactly this. The failure was a test-setup bug (reservation created against a SCHEDULED slot). No PRD silence.

  3. `test_09_party_bookings.py` / `test_sanitation_overdue_blocks_party_confirm` (24h HELD expiry + sanitation gate) — Covered verbatim by PRD §3.7 line 183 (*"the operations sweep expires it to `EXPIRED` once the logical clock reaches 24 hours past its `created_at`"*, and confirm *"requires ... no `OVERDUE` sanitation task on that room (else `ERR_SANITATION_OVERDUE`, HTTP 422)"*), §3.7-sanitation line 193 (*"an `OVERDUE` task on a room blocks party confirmation there with `ERR_SANITATION_OVERDUE`"*), and §3.9 line 205 (*"expires unpaid `HELD` party bookings at 24 hours of age"*). Implementation: `app.py:2415-2424` (sweep expires HELD bookings at `created_at + 24h`), `app.py:1861-1862` (confirm on non-HELD booking → `ERR_INVALID_STATE`), and `app.py:1866-1868` (OVERDUE task on room → `ERR_SANITATION_OVERDUE`). The failure was a test-setup bug (clock jumped after booking creation, so the sweep expired the booking before confirm). No PRD silence.

- **Per-edit pre-edit search log:** zero edits were made, so per the instructions the per-diff-item verbatim-coverage list above substitutes for the (a)/(b)/(c) log. Impl paths read for verification: `app.py:103,105,119` (error table), `app.py:1500-1541` (visit creation gates), `app.py:1625-1634` (check-in gates), `app.py:1855-1875` (party confirm gates), `app.py:2410-2430` (sweep: no-show, hold expiry, sanitation flagging).

## Step 9: Complete PRD — 2026-08-10T06:17:17.430Z

Done. PRD_COMPLETED.md written at /home/ubuntu/github/CodingPRD/tasks/task_0963_indoor_playground_kids_cafe/workspace/PRD_COMPLETED.md — all changes are in-paragraph inserts/revisions; line count unchanged (325 lines), +3,334 chars over PRD_FINALIZED.md (48,187 → 51,521).

Summary:

- Source: PRD_FINALIZED.md (325 lines, 48,187 chars) vs PRD_COMPLETED.md (325 lines, 51,521 chars); char-delta +3,334.
- Counts: 18 ambiguity-pins, 5 mismatch-revisions.

Ambiguity-pins (inserts):
- §2.1 — insert — ambiguity — Anonymous exemption applies only when X-User-Role header is absent; a present-but-undeclared role still yields ERR_UNAUTHENTICATED — implementation/app.py:237-241
- §2.3 — insert — ambiguity — out-of-range limit/offset clamped into range, non-integer values fall back to defaults, never an error — implementation/app.py:361-380
- §2.7 — insert — ambiguity — stale-version check evaluation point per workflow (waiver: after guardian resolves; slot resize: after slot resolves, before capacity floor; booking create: after status/child-count/conflict checks) — implementation/app.py:1227, 1408, 1807
- §2.8 — insert — ambiguity — a missing or mistyped identifier yields ERR_VALIDATION before the existence tier is reached — implementation/app.py:1493-1505, 1786-1797
- §3.1 — insert — ambiguity — birth_date must be a parseable ISO date else ERR_VALIDATION — implementation/app.py:1180-1181
- §3.3 — insert — ambiguity — manual close accepted from SCHEDULED or OPEN; closing an already-CLOSED slot is ERR_INVALID_STATE — implementation/app.py:1455-1456
- §3.3 — insert — ambiguity — capacity-resize patch is not gated on the slot's status — implementation/app.py:1399-1429
- §3.3 — insert — ambiguity — an evacuated never-prepaid visit records final_charge_cents but keeps payment_status PENDING; no collection or refund — implementation/app.py:851-856
- §3.3 — insert — ambiguity — close compensation is one +200 ADJUSTMENT per affected guardian regardless of how many of their visits were affected — implementation/app.py:862-876
- §3.4 — insert — ambiguity — no child-belongs-to-guardian consistency check at visit creation — implementation/app.py:1503-1505
- §3.4 — insert — ambiguity — sock_method/grip_socks_order_id supplied at booking are ignored; reservations are stored with sock_method NONE — implementation/app.py:1570-1571
- §3.4 — insert — ambiguity — walk-ins may set use_credit subject to the same membership and credit-availability gates — implementation/app.py:1556-1561
- §3.6 — insert — ambiguity — lines must be a non-empty array, quantity integer with no minimum, negative points_to_redeem is ERR_VALIDATION — implementation/app.py:2052-2063, 2073-2074
- §3.6 — insert — ambiguity — zero-point redemption writes no REDEEM ledger entry — implementation/app.py:2137-2138
- §3.6 — insert — ambiguity — zero-point earn writes no EARN entry at serve or at visit check-out — implementation/app.py:1694, 2179
- §3.7 — insert — ambiguity — confirm-time conflict re-check excludes the booking itself — implementation/app.py:1871-1873
- §3.8 — insert — ambiguity — reopening a RESOLVED incident retains recorded child_reunited and resolution_note — implementation/app.py:2366-2368
- §3.9 — insert — ambiguity — tiers_recomputed counts every guardian evaluated each run, changed or not — implementation/app.py:2458-2461

Mismatch-revisions:
- §2.4 — revise — mismatch — clock may be set to any instant; no requirement that it be later than the current reading ("advances" was wrong) — implementation/app.py:2465-2475
- §3.3 — revise — mismatch — checked_out_at is stamped only on evacuated visits, not on cancelled reservations — implementation/app.py:837-842 vs 852
- §3.5 — revise — mismatch — check-in gate order is slot-open, waiver, grip-socks, then window (PRD listed window second, contradicting §2.8 tiers and impl); success also records the supplied grip_socks_order_id — implementation/app.py:1633-1656
- §3.9 — revise — mismatch — lifetime_points accumulates EARN + positive ADJUSTMENT + signed REVERSAL points (redemption restores add back); negative adjustments never reduce lifetime — implementation/app.py:461-470
- §3.9 — revise — mismatch — manual adjustment floors only lifetime_points; points_balance is the raw signed ledger sum and may go negative (PRD said both floored) — implementation/app.py:459-462, 515-528
