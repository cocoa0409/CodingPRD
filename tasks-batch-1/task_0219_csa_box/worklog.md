# Worklog — task_0219_csa_box

## Step 1: Create Task Directory — 2026-06-07T03:02:55.000Z

Created `tasks/task_0219_csa_box/` and `tasks/task_0219_csa_box/workspace/` using the pre-allocated path verbatim (index-scan skipped per orchestrator instructions).

## Step 2: Generate Scaffold — 2026-06-07T03:21:47.000Z

Generated all three scaffold artifacts for `task_0219_csa_box` (Community Supported Agriculture box subscription system) at the **Expert** difficulty tier. `scaffold_lint.py` returns **`VERDICT: clean lint`** and no forbidden concurrency vocabulary is present.

**Files written** (all under `tasks/task_0219_csa_box/`):
- `SCAFFOLD.yaml` (§1.0–§1.7)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

**Complexity profile**: primary archetype quota_allocation + secondary temporal_windowing; flat entity topology; parallel state-machine shape; peer_roles RBAC; immediate consistency; layers = optimistic_concurrency, cascading_side_effects, dual_variant_calculation, derived_field_reconciliation.

**Coverage counts**:
- **Entities**: 12 — Season, PickupSite, ShareType, AddOn, Member, Subscription (parallel billing × fulfillment axes), SubscriptionAddOn (junction), WeeklyBox (cyclic), VacationHold (refund/swap, self-referential swap target), WaitlistEntry (branching), WorkShareShift, LedgerEntry (append-only, `common_fields:false`).
- **State machines**: 5 — Season (linear), Subscription (parallel dimensions + cancel cascade), WeeklyBox (cyclic SCHEDULED⇄HELD), WaitlistEntry (branching OFFERED→{CONVERTED,DECLINED,EXPIRED}), WorkShareShift.
- **Concurrency rules**: 2 OCC-on-Season races (confirm-stale-season, promote-stale-season), both 412/ERR_STALE_VERSION.
- **Calculations**: 4 — season_share_price (sliding-scale tiered), outstanding_balance (provisional/finalized variants, pinned circular-look eval order), workshare_credit (daily-cap threshold), hold_refund_value (remainder-last waterfall).
- **Validations**: 17 priority-ordered rows across auth/existence/state/business categories.
- **Endpoints**: 50 (includes single-resource GETs for segment derivation, filtered-list FK reverse-reachability params, and a `/_clock/set_current_utc` test-driving endpoint).
- **Errors**: 18 domain-specific codes.
- **Roles**: 5 — FarmManager, DeliveryCoordinator, Member (entity_backed:Member), PlatformAdmin (opaque), Anonymous.

**§1.8 Difficulty Design**: 9 rule_ids × 2 instances = **18 instances**, each grounded in declared §1.1–§1.7 elements, with structured `setup_api_calls`/`trigger`/`assert` chains and formula-derived asserts pre-computed as literals (e.g., 40000/50000/62500 tier prices; 6000+3000 daily-cap straddle; 4167/4166 remainder split; 39833 pinned-order balance).

**§1.9 Corner Design**: 9 sections, **39 instances** (30 full test_recipes + 9 `excluded_because` stubs each citing a valid §1.8 instance) covering entity CRUD/defaults/computed/immutability, invalid-transition/terminal-lockdown/initial-state, calculation correctness, validation violations, endpoint/pagination/envelope, error triggerability, RBAC denials, OCC happy-path+stale, derived-field reconciliation, and immediate consistency.

Design note: `api_prefix` is `/` (root) because the flat multi-resource topology spreads collections across many top-level paths; required for the lint's collection-segment derivation and FK reverse-reachability check to pass.

## Step 3: Copy Shared Files — 2026-06-07T03:22:00.000Z

Copied `INSTRUCTION.md` → `tasks/task_0219_csa_box/workspace/INSTRUCTION.md` (bash, no subagent).

## Step 4: Generate PRD — 2026-06-07T03:25:30.000Z

**Output:** `workspace/PRD.md` (280 lines).

### Sections covered
- **§1 Introduction** — CSA domain, dual-axis lifecycle, dual-dimension capacity, sliding-scale pricing, temporal fulfillment.
- **§2 Global Specs** — 9 subsections: 2.1 RBAC (5 roles + identity translation: `Member` entity-backed, other four opaque), 2.2 fixed response envelope, 2.3 pagination, 2.4 common resource properties (`LedgerEntry` only `common_fields: false` — id+created_at), 2.5 monetary precision/round-half-up, 2.6 nested retrieval + season cohesion, 2.7 state validity + priority ordering, 2.8 cascading side effects, 2.9 OCC on the two capacity-sensitive writes.
- **§3 Business Logic** — 11 subsections by lifecycle/entity: season+catalog, members+sliding scale, subscribing→confirm, ledger+outstanding balance, add-ons, weekly fulfillment, vacation holds, waitlist, working shares, cancellation cascade, simulated clock.
- **§4** — 50-endpoint table (4 cols). **§5** — 18-error table (2 cols).

### Coverage (all contracts PASS)
- **Contract 1 (Field-Name):** 50/50 entity fields + endpoint identifiers verbatim in backticks (incl. `expected_season_version`, `to_iso8601`, FK/query params). 0 missing.
- **Contract 2 (Rule):** All state machines' transitions expressed; all 4 calculations rendered as reconstruction-passing prose — `season_share_price` (tier multipliers 0.80/1.00/1.25, pinned-at-confirm), `outstanding_balance` (4-step fixed eval order + provisional/finalized variants), `workshare_credit` (1500¢/hr, 6h daily cap, created_at-ASC same-date, under-cap/straddle variants), `hold_refund_value` (floor + remainder-to-earliest-weeks). Both OCC rules framed via `expected_season_version`/`ERR_STALE_VERSION`/412. Dual-scope validations enumerated. 3-hop cancellation cascade stated.
- **Contract 3 (§3 Path Purity):** 334 §3 backtick tokens, 0 path/method violations.
- 43/43 enum values present; all 18 error IDs surface in §2/§3 prose with trigger conditions.

### Notable scattering choices
- Confirm's input params split: create-params in 3.3, OCC `expected_season_version` in 2.9, capacity/temporal gates across 2.7 + 3.3.
- Constants embedded in narrative (48-hour offer window, 1500¢/hr, 6h cap, 7-days-per-week-index delivery-date derivation).
- `delivery_surcharge_cents × week_count` surcharge and `remaining_weeks` add-on fallback placed inside workflow narratives.
- FK relationships expressed only through actions/payloads; no schema tables in §3.
- Both withheld design files were not opened, grepped, or referenced.

## Step 5: Generate Unit Tests — 2026-06-07T03:48:00.000Z

Generated complete test infrastructure under a strict design-index-only contract.

### Tests emitted: 66 total
- **Queue A (Difficulty): 36 tests** — all 18 difficulty instances covered with exactly 2 tests each (9 rules × 2 instances). Rules: dual_variant_calc, combinatorial_formula, non_linear_state_machine, transitive_cascade, priority_pair_validation_conflict, boundary_precision_check, cross_entity_state_dependency, resource_temporal_overlap, compensating_invariant.
- **Queue B (Corner): 30 tests** — all 30 non-stub corner instances, 1 test each, across sections entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_complexity_layers, consistency_model.

### Instances skipped: 0 non-stub
All 18 difficulty + 30 corner non-stub instances passed the PRD-first two-condition filter. The 9 corner `excluded_because` stubs were correctly NOT translated; all 9 `difficulty_instance` cross-references resolve.

### test_helpers/ files created (9)
`__init__.py`, `types.py` (entity TypedDicts + 11 enums; LedgerEntry omits updated_at/version per common_fields:false), `api_client.py` (49 endpoint methods), `api_errors.py` (18 error IDs + HTTP status map), `assertions.py`, `factories.py`, `constants.py`, `test_users.py` (Member entity_backed → make_member_headers(id); other roles opaque), `fixtures.py` (composite setup tiers).

### Verification
- All files byte-compile; test_helpers imports cleanly against `prd_bench_local_runner`.
- `pytest --collect-only`: 66 tests, 0 errors. Every test has exactly one verbatim Design: tag resolving to a real instance. All 80 PRD citations survive literal grep. No skip/xfail anywhere.
- Key finding: PRD §3.3 encodes explicit ordered confirm-gate priority (ERR_SIGNUP_CLOSED → ERR_SITE_CAPACITY_FULL → ERR_SEASON_CAPACITY_FULL) + §2.7 cross-check ordering, making both priority_pair_validation_conflict instances uniquely-derivable.

## Step 6: Generate Implementation — 2026-06-07T03:48:00.000Z

Built a complete Python + Flask in-memory REST API at `workspace/implementation/`.

### Files created (12)
`start.sh` (foreground; reads $PORT default 10000, binds 0.0.0.0, guards pip install on `import flask`, `exec python3 app.py`), `requirements.txt` (Flask 3.0.3), `app.py` (1193 lines — 50 endpoints, error handlers, RBAC, ownership, state machines, calc orchestration), `db.py` (module-level dicts, simulated clock, monotonic sequence; no seeding; reset() clears all), `calc.py` (4 rules, Decimal + ROUND_HALF_UP), `services.py` (ledger posting, outstanding-balance recompute, counters, box delivery dates, fulfillment bubble-up, clock-driven transitions), `models.py`, `response.py`, `errors.py`, `middleware.py`, `serialize.py`, `validation.py`.

### Endpoints: all 50 (route count confirmed = 50; store confirmed empty at import)
Season (CRUD+open/close/promote-waitlist), PickupSite, ShareType, AddOn, Member, Subscription (CRUD+confirm/cancel), SubscriptionAddOn (attach/detach/list), WeeklyBox (list/pack/deliver), VacationHold (place/release/list), WaitlistEntry (join/accept/decline/list), WorkShareShift (schedule/complete/mark-no-show/list), LedgerEntry list, payments, `/_clock/set_current_utc`.

### State machines & calculations (verified)
- Parallel subscription axes: billing_status & fulfillment_status tracked independently; first DELIVERED box flips both; all-terminal bubble-up → COMPLETED.
- WeeklyBox cyclic SCHEDULED⇄HELD + pack/deliver/skip; SWAP target doubles item_count at pack.
- Sliding-scale pricing pinned at confirm (0.80/1.00/1.25, round-half-up).
- Outstanding balance fixed eval order (charges − hold-refunds − wallet-applied − payments, floored at 0); provisional & finalized variants.
- Hold refund remainder-last pro-rata (lowest week_index +1 cent), reconciles to season_price; release reverses.
- Work-share credit 1500¢/hr with 6h daily UTC cap (straddle verified 4h→6000, +4h→3000).
- Cancellation 3-hop cascade: boxes→SKIPPED, holds→RELEASED, add-ons→DETACHED, refund posted, counters decremented.
- Clock-driven transitions: HELD-past-delivery→SKIPPED/CONSUMED, OFFERED-past-expiry→EXPIRED.

### Key design decisions
- Response envelope verbatim from scaffold; error body {error_id,message}; ISO 8601 UTC, 3 fractional digits.
- Derived counters always recomputed, never set directly; each recompute bumps owner version/updated_at per §2.8.
- Validation priority per §2.7: auth(401)→role(403)→ownership(403)→existence(404)→cohesion(409)→state(409)→business/temporal→request-body→OCC(412).
- OCC on expected_season_version for confirm + promote-waitlist only; mismatch→412.
- Ownership enforced only for Member actors (other roles opaque); Anonymous carries no X-User-ID.
- In-memory only; start.sh reboot wipes all state (verified 0 seasons after restart). No 500s observed.

## Step 7: Run Tests and Iterate — 2026-06-07T04:05:00.000Z

Final: 8/8 rounds at 65/65, zero failures, zero errors (verified on disk).

**Iterations run:** 5 full 8-round parallel sweeps (1 baseline diagnosis + 4 verification sweeps).

**Starting state:** 63/66 passing per round, deterministic across all 8 rounds. Three distinct failures, all infra/logic issues unmasked once the boot-latency problem was addressed.

**Tests deleted (1):**
- `test_waitlist_accept_after_expiry_rejected` (test_03_precedence_and_boundaries.py) — **STEP 1b unique-derivability failure / ERROR-PRECEDENCE-SILENCE collapse contradicted by a PRD-mandated side effect.** Test promotes a waitlist entry, advances the clock past `offer_expires_at`, then expects `accept` to return `ERR_OFFER_EXPIRED`. But PRD §3.11 verbatim mandates that advancing the clock fires every due clock-driven transition, moving any OFFERED entry whose `offer_expires_at` has passed to `EXPIRED`. The lapse boundary equals the accept-expiry boundary, so the entry is always already EXPIRED when accept runs → `ERR_INVALID_STATE` (priority 6) pre-empts the temporal `ERR_OFFER_EXPIRED` (priority 10). No PRD-faithful impl can reach `ERR_OFFER_EXPIRED` through the documented clock path. Scaffold driver: WaitlistEntry OFFERED→EXPIRED fork + `ERR_OFFER_EXPIRED` accept gate.

**Fixes applied to test_suite/ (2):**
- `test_05_state_machine_corners.py::test_pack_box_from_held_returns_invalid_state` — **TEST BUG (STEP 2).** Fixture confirmed at clock `2026-08-25` then placed a hold on the week-1 box (delivery `2026-07-01`, already passed) → impl correctly returned `ERR_HOLD_WINDOW_PASSED` during setup. Changed clock to `2026-06-15` (before week-1 delivery) so the hold succeeds and the intended pack-from-HELD state check is exercised.
- `test_06_calc_and_validation_corners.py::test_swap_target_earlier_week_rejected` — **TEST BUG (STEP 2).** Same root cause: clock `2026-08-25` with a hold on the week-5 box (delivery `2026-07-29`, passed) tripped `ERR_HOLD_WINDOW_PASSED` (priority 8) before the swap-target check (priority 9). Changed clock to `2026-06-15` so hold-window passes and `ERR_INVALID_SWAP_TARGET` is reached.

**Fixes applied to implementation/ (1):**
- `app.py` (module top, before `app.run`) — **Boot-latency root cause.** Added a `socket.getfqdn` short-circuit for unspecified hosts (`""`, `0.0.0.0`, `::`). Werkzeug's dev server calls `getfqdn("0.0.0.0")` during `server_bind` for its startup banner; on macOS this blocked ~5s on a reverse-DNS timeout, paid on every per-test reboot — causing systematic "API server could not be restarted" errors and mid-request `BadStatusLine` aborts under the 8× concurrent sweep. Cold-boot time-to-ready dropped 5.84s → 0.23s (~25×), eliminating both.

**Final result:** 3 consecutive clean 8-round sweeps. Current on-disk sweep: 8/8 rounds at 65/65, zero failures, zero errors.

## Step 8: Finalize PRD — 2026-06-07T04:10:00.000Z

**Outcome:** PRD_FINALIZED.md produced and byte-identical to PRD.md — 280 vs 280 lines, 0% delta, 0 edits. None of the three `<step_7_diff>` items revealed a PRD silence or mismatch; every behavior they hinge on is already uniquely determined by existing PRD prose.

### Per-item analysis
- **Impl fix — app.py `_fast_getfqdn` (lines 19–29)** — pure Werkzeug reverse-DNS boot-latency short-circuit; affects only the dev-server startup banner host, no PRD-visible behavior. → No edit.
- **Deleted test `test_waitlist_accept_after_expiry_rejected`** — its expectation contradicts behavior PRD already mandates: §3.11 fires OFFERED→EXPIRED when offer_expires_at passes; §2.7 ranks state-validity (ERR_INVALID_STATE) above domain temporal checks (ERR_OFFER_EXPIRED); §3.8 gates accept on OFFERED. Jointly force ERR_INVALID_STATE, matching impl. → No edit.
- **Two test_suite clock fixes** — pure fixture bugs: clock 2026-08-25 (past box delivery) tripped the already-documented ERR_HOLD_WINDOW_PASSED gate (§3.7, boundary now>=delivery) before the intended check. Gate, boundary, and ordering all already in PRD. → No edit.

Two candidate edits were enumerated under the NO-NEW-MISMATCH rule (hold-window vs swap-target order; ERR_INVALID_STATE vs ERR_OFFER_EXPIRED order) and both abandoned — outcomes already prose-derivable; explicit priority sentences risked over-narrowing release_vacation_hold (no swap-target gate). Left verbatim.

## Step 9: Complete PRD — 2026-06-07T04:16:00.000Z

**Files:** Source PRD_FINALIZED.md vs PRD_COMPLETED.md — 280 → 280 lines (unchanged); 45,856 → 47,067 chars (+1,211).

**Counts:** 7 changes — 5 ambiguity-pins, 2 mismatch-revisions.

**Per-change:**
- §2.4 (system-managed fields) — insert — ambiguity — pinned `version`'s initial value as `1` — models.py:23
- §3.3 (confirmation cascade) — revise — mismatch — `CHARGE_SURCHARGE` posted only when `delivery_surcharge_cents × week_count` is non-zero (0-surcharge HOME_DELIVERY posts none) — app.py:522
- §3.4 (ledger/payments) — insert — ambiguity — payment endpoint negates supplied positive `amount_cents`, returns the new `PAYMENT` ledger entry as `data` with `201 Created` — app.py:1185,1189-1191
- §3.5 (add-on detach) — insert — ambiguity — offsetting credit is `CREDIT_HOLD_REFUND` of `weekly_price_cents × remaining_weeks` (recomputed at detach; season `week_count` when no boxes), posted only when non-zero; detach defined only from `ATTACHED` (else `ERR_INVALID_STATE`) — app.py:674-691
- §3.7 (hold release reversal) — insert — ambiguity — offsetting charge is a `CHARGE_SEASON` with positive `amount_cents` equal to that week's per-week refund value — app.py:949
- §3.8 (waitlist accept) — insert — ambiguity — created subscription's `working_share_opt_in` defaults false; accept returns the updated `CONVERTED` waitlist entry as `data`, not the new subscription — app.py:1034,1042
- §3.10 (cancellation cascade) — revise — mismatch — counters reconciled by recompute from surviving CONFIRMED/ACTIVE subscriptions (decrement of one when cancelling a confirmed sub; no change for a never-confirmed PENDING_PAYMENT sub) — app.py:604-607, services.py:70-91

Left unchanged (already uniquely pinned & matching impl): calculation formulas, state-machine transitions, error precedence, confirm-time counter increments. Impl-only conveniences not contradicting PRD (extra list filters, real-wall-clock created_at, float-accepting hours, empty-email rejection, clock-endpoint body) were not over-specified.

---

## Pipeline complete

All 9 steps finished. Final artifacts in `tasks/task_0219_csa_box/`: SCAFFOLD.yaml + SCAFFOLD_DIFFICULTY_DESIGN.yaml + SCAFFOLD_CORNER_DESIGN.yaml, worklog.md, test_helpers/ (9 files), test_suite/ (7 test files + conftest, 65 tests), workspace/{INSTRUCTION.md, PRD.md, PRD_FINALIZED.md, PRD_COMPLETED.md, implementation/}. Final test status: 8/8 parallel rounds at 65/65 passing.
