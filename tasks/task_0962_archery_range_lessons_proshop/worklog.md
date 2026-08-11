# Worklog — task_0962_archery_range_lessons_proshop

## Step 1: Create Task Directory — 2026-08-10T00:00:00.000Z

Pre-assigned output folder `tasks/task_0962_archery_range_lessons_proshop` and its `workspace/` subdirectory already existed; Step 1 auto-index scan skipped per invocation instructions.

## Step 2: Generate Scaffold — 2026-08-10T02:37:00.000Z

All three scaffold artifacts are generated, YAML-valid, and pass `scaffold_lint.py` with a clean verdict. No sibling task was consulted — the design was derived purely from the scenario text and the skill spec.

**Lint verdict (verbatim):**
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(Coverage: 72 endpoints, 16 entities, 19 §1.8 instances, 35 §1.9 instances, 436 calls scanned.)

**Files written** (under `/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop/`):
- `SCAFFOLD.yaml` — §1.0–§1.7 only (no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single top key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` — single top key `scaffold_corner_design`

**Summary of the generated design** (calibrated above expert level):
- **16 entities**: Member (self-referential guardian FK for minors), Waiver, Lane, RangeSession (parallel `session_status` × `payment_status` dimensions), SessionParticipant, PunchCard, RentalItem, RentalAgreement, Coach, Lesson, League, LeagueEntry, ScoreCard, ShopProduct, Sale, RepairOrder.
- **12 state machines**, including a Lesson negotiation cycle (REQUESTED↔COUNTERED), a ScoreCard dispute cycle (VERIFIED→DISPUTED→SUBMITTED), RepairOrder approve/decline branching, and system sweeps (no-show, waiver expiry) driven by a logical-clock endpoint with pinned default `2026-05-01T00:00:00Z`.
- **8 calculation rules** with all constants/rounding pinned: dual-variant session fee (QUOTED forward-looking vs FINAL metered), dual-variant league standings (SCRATCH vs HANDICAP), nested-rounding sale totals (per-line-then-sum pinned), circular-looking prize pool (share-from-gross pinned), tiered cancellation refund, rental settlement with late/damage fees, rush/tier repair quotes, lesson tier pricing.
- **72 endpoints**, **47 error codes**, **10 ordered validation priorities** (safety > constraint > temporal > referential > fiscal), **7 roles** (hierarchical override, entity-backed Member/Coach), **2 OCC concurrency rules** (scorecard correction, repair re-quote, both 412 ERR_STALE_VERSION).
- **§1.8 difficulty design: 19 instances across all 9 rules** (dual-variant on two entity domains; combinatorial modes (a)/(b)/(c); two cyclic machines; depth-3 suspension cascade and depth-2 league-cancel cascade; state-vs-fiscal and safety-vs-constraint priority conflicts; punch-exhaustion and 24h-refund boundary precision; Session→Waiver and Lesson→Coach cross-entity gates; lane half-open vs coach buffered-interval overlap; punch-count and wallet compensating invariants). All numeric asserts are pre-computed literals (e.g., quoted 2160 vs final 1200; standings 303 vs 306; sale subtotal 1054 vs sum-then-round 1055; pool 17000; settlement 9700; quote 11500).
- **§1.9 corner design: 35 active instances + 9 excluded_because stubs** across entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers (OCC stale-version pairs, reservation reconciliation), and consistency model.


## Step 3: Copy Shared Files — 2026-08-10T02:38:00.000Z

Copied `./INSTRUCTION.md` to `tasks/task_0962_archery_range_lessons_proshop/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-10T02:42:30.000Z

PRD generated and confirmed on disk at `/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop/workspace/PRD.md` (331 lines, ~49 KB). The two withheld design-index files were never opened or referenced.

## Summary

**Structure**: §1 Introduction (2 paragraphs) → §2 Global Specifications with 10 domain-derived subsections (RBAC, verbatim §2.2 response envelope, pagination, common resource properties, logical clock & epoch sweep, money/rounding, OCC, validation priority ordering, safety compliance gate, nested resource retrieval) → §3 Business Logic with 9 subsections (membership/strikes cascade, waivers, range sessions & metered fees, cancellation/no-show refunds, punch cards, rentals/fitting/settlement, lessons & negotiation cycle, leagues/scoring/standings, pro-shop sales & repair bench) → §4 endpoint table (69 rows, 4 columns) → §5 error catalogue (47 rows, 2 columns).

**Coverage**: all 17 entities, 12 state machines (every transition's preconditions, side effects, and cascades — including the 3-hop suspension cascade and 2-hop league-cancel refund cascade), all 8 calculations with pinned evaluation orders expressed as reconstructible prose (dual QUOTED/FINAL lane-fee variants, per-line-rounding-then-sum sale total, range-share-from-gross prize pool, scratch/handicap standings, refund tiers, rental settlement, repair quote with rush fee, lesson fee), both OCC rules with exact endpoints/fields/error, 10-level validation priority ordering in prose, and all 69 endpoints in §4.

## Hard Contract Reports

```
Field coverage check:
- entities[].fields + endpoints[].input/query_params + nested line-item fields: 97 required, 97 present, 0 missing
Status: PASS

Rule coverage check:
- validations[] priority ordering: 10 checked, 10 expressed in prose (§2.8), 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write endpoint + expected_*_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 31 checked, 31 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (formulas, constants, precision, variants), 0 missing
- validations[] conditions: 10 checked, 10 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: all expressed in workflow narratives, 0 missing
- entities[].fields[] structured content: defaults, ranges, enums, computed sources all reconstructible from prose, 0 missing
- sibling-branch symmetry: counter cycle (coach/member), accept/confirm paths, cancel-from-3-states, league cancel from OPEN/CLOSED all rendered with equal density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 493
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Zero-silence audit: all 47 error IDs appear in §2/§3 prose; all state enum values and all field/parameter enum values (`BASIC/PLUS/ELITE`, `WALK_IN/RESERVATION`, `SCRATCH/HANDICAP`, etc.) appear verbatim; §2.2 emitted byte-identical to the canonical block.

## Step 5: Generate Unit Tests — 2026-08-10T02:58:00.000Z

Both output directories exist on disk and everything is verified. Summary:

## Summary

**Total tests emitted: 71** (all collected cleanly by pytest, all modules import, no skip/xfail/skipif markers anywhere).

**Queue A (difficulty) coverage: 18 of 19 instances translated, 2 tests each = 36 tests; 1 skipped.**
- Skipped: `dual_variant_calc/standings_scratch_vs_handicap_divergence` — fails unique derivability. PRD §3.8 states only that the standings response "carries the echoed `variant` and the ranked `rows`"; it never pins the row schema. The instance's assertions require `rows[0].member_id`, `handicap_index == 18`, and `adjusted_points == 303`, but a PRD-only implementer could legitimately key rows by `league_entry_id` or name the computed fields differently. No weakening emitted; gap stays a gap.

**Queue B (corner) coverage: all 35 non-stub instances translated, 1 test each; all 9 `excluded_because:` stubs skipped** (cross-references verified to resolve to real difficulty instances).

**test_helpers/ files** (at `/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop/test_helpers/`):
`__init__.py` (barrel), `types.py` (16 entity TypedDicts + status enums, all with version/updated_at per common_fields), `api_client.py` (ApiClient with one method per PRD §4 endpoint), `api_errors.py` (all 47 error IDs + HTTP map, registered via `set_error_http_status_map`), `assertions.py` (per-entity assertions + punch-card/pool/sale invariant checkers), `factories.py`, `constants.py` (all PRD §3 calculation constants), `test_users.py` (opaque-role shared constants + `make_member_headers`/`make_coach_headers` per-instance builders for the two entity-backed roles), `fixtures.py` (composite setups: ready members, booked/checked-in sessions, punch-card sessions, closed leagues with scorecards, rentals, coaches/lessons, shop/repair).

**test_suite/ files** (at `.../test_suite/`): `conftest.py` + 10 domain-organized files (membership/waivers, session booking/lifecycle, session fees/lane overlap, punch cards/cancellation refunds, safety strikes/priority, rentals, lessons, leagues/scorecards, pro-shop/repairs, envelope/pagination/anonymous).

**Stage-2 design-tag audit: PASS.** Programmatic check: every one of the 71 tests has exactly one `Design:` line; all tags resolve verbatim to real instance names; queue A ≥2 tests/instance (except the documented skip); queue B ≥1 per non-stub; 0 tests on stubs. Verbatim-citation sweep: all 123 quoted citation fragments across all docstrings survive whitespace-normalized literal match against PRD.md; no "scaffold" references in generated code.

**Three judgment calls to be aware of:**
1. `Corner/state_machines/session_cancel_after_close_rejected`: PRD §3.3 says terminal-state operations surface `ERR_SESSION_ALREADY_CLOSED`, but §3.4 says "cancelling from any other state is `ERR_SESSION_NOT_BOOKED`" — an internal PRD contradiction. Resolved with `validate_error_is_one_of([ERR_SESSION_ALREADY_CLOSED, ERR_SESSION_NOT_BOOKED])` plus strict state assertions (still CLOSED, `cancellation_refund_cents` null).
2. Absolute `version` literals in the design yamls (e.g., `version == 1`, `== 4`) are not uniquely derivable — PRD §2.4 says version "starts at its initial value" without naming it. Version assertions were translated as PRD-verbatim increment-by-one relationships against captured versions instead.
3. Two design-recipe setup gaps fixed per PRD: `lane_capacity_third_archer_rejected` (guest g1 pays from their own wallet per §3.3, so g1 is funded in setup) and `checkin_gated_by_participant_waiver_state` (yaml's 7840 wallet expectation assumed PLUS tier but the payload is BASIC; assertions use the PRD-derived quoted fee 2400 / wallet 7600).

## Step 6: Generate Implementation — 2026-08-10T02:58:00.000Z

Done. The implementation is complete and verified.

## Summary

**Files created** in `/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop/workspace/implementation/`:
- `app.py` (2031 lines, 72 routes) — single-file Flask app: envelope/error handling, auth, logical clock, all routes, calculations, cascades
- `start.sh` — executable; guarded `pip install` (no-op once Flask is importable), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000), foreground
- `requirements.txt` — `flask`

**Boot verification**: `PORT=<free> bash start.sh` boots in ~1s; ran a 58-assertion smoke suite covering auth (401/403), member/minor/guardian registration, waiver signing and consent errors, wallet adjustments, lanes, booking windows, half-open lane overlap, participant add (wallet + punch), capacity, check-in window, close reconciliation, cancellation refund tiers, no-show sweep, punch-card purchase/exhaust/restore, coach/lesson negotiation cycle, league entries/pools/close/scorecard cycle/OCC/standings, pro-shop sales with pinned rounding, repair quote/approve/pickup with OCC and stock reservation, and the 3-strike suspension cascade. All pass. Fresh-process boot confirmed repeatedly (state starts empty each launch; no seeding anywhere).

**Endpoints implemented**: all 70 PRD endpoints (clock, members/waivers/punch-cards, lanes, range sessions + participants + check-in/close/cancel, rental items/agreements/return/settle, coaches, lessons confirm/counter/accept/cancel/complete, leagues/entries/close/cancel/standings, scorecards PUT/verify/dispute/lock, shop products, sales, repair orders intake/quote/approve/decline/complete/pickup).

**State machines**: Member (ACTIVE↔SUSPENDED with 3-strike auto-suspend + 3-hop cascade incl. direct rental voiding), Waiver (ACTIVE→EXPIRED sweep / →REVOKED), RangeSession (BOOKED→CHECKED_IN→CLOSED, →CANCELLED, →NO_SHOW; parallel payment_status UNPAID/PAID/REFUNDED), SessionParticipant (ACTIVE→REFUNDED/FORFEITED), PunchCard (ACTIVE↔EXHAUSTED boundary), RentalItem/Agreement (incl. VOIDED cascades), Coach, Lesson (REQUESTED↔COUNTERED negotiation), League (OPEN→CLOSED→COMPLETED auto-transition on all-locked; cancel refund cascade), ScoreCard (SUBMITTED↔VERIFIED/DISPUTED→LOCKED, OCC self-transition), RepairOrder (INTAKE→QUOTED→IN_REPAIR→READY→PICKED_UP, DECLINED branch with stock release).

**Calculations** (all `Decimal` ROUND_HALF_UP): session fee QUOTED/FINAL variants (30-min blocks, peak 1.25 at UTC 17–20 keyed on start_at, participant-tier discount, 1200 floor, +300 walk-in surcharge after floor in QUOTED only), sale totals (per-line round → sum → 10% volume at ≥10000 → 8.25% tax), league pools (gross → 15% share from gross → pool), standings SCRATCH/HANDICAP (avg, 1.2×(300−avg) handicap, full tie-break chain), cancellation refund tiers (24h/4h boundaries inclusive-upward, punch restore iff ≥4h or system cancel), rental settlement (day-granularity billable/late days, 500/day late fee), repair quote (30-min labor blocks, tier discount, 25% rush <48h), lesson fee, punch-card pricing.

**Key conventions honored**: `meta`/`response_type`/`data` envelope, `limit`/`offset`/`total_count`/`has_more` pagination (default 10, clamp 1–100, created_at-ascending), X-User-ID/X-User-Role auth with entity-backed ownership (403), validation priority auth→authz→existence(left-to-right)→shape→state→waiver/consent→constraints→booking-window→availability→funds, OCC via `expected_scorecard_version`/`expected_repair_order_version` → ERR_STALE_VERSION 412, logical clock default 2026-05-01T00:00:00Z with no-show + waiver-expiry epoch sweep, common fields id/created_at/updated_at/version (starts 1, bumps on every mutation including cascaded children).

**Judgment calls on PRD-silent edges** (no test-visible contract specified): CLOSED session ops surface ERR_SESSION_ALREADY_CLOSED vs ERR_SESSION_NOT_BOOKED for other non-BOOKED states; coach activate/deactivate from the wrong state → ERR_INVALID_REQUEST; cancellation_refund_cents counts wallet cents only (punch restores are non-monetary) with payment_status→REFUNDED iff that sum > 0; re-quoting a QUOTED repair releases the prior reservation before reserving the new parts.

## Step 7: Run Tests and Iterate — 2026-08-10T03:03:00.000Z

## Summary

**Iterations run:** 2 (initial 8-round sweep → 1 fix → verification 8-round sweep, all 8 rounds clean at 71/71).

**Tests deleted (full):** none.

**Tests modified (partial-coverage split, STEP 1c):**
- `test_suite/test_04_punch_cards_and_cancellation_refunds.py::TestPunchConsumeAndCancelRestoreInvariant::test_cancel_marks_session_refunded_and_participant_refunded` — removed the `payment_status == "REFUNDED"` assertion. **Silence/collapse pattern:** DEFAULT/BRANCH silence on the zero-money branch — for a punch-only voluntary cancellation the refunded amount is 0, and PRD §3.4 pins the `REFUNDED` transition verbatim only to "whenever the refunded amount is greater than zero"; the "punch restore counts as a refund" wording exists only in §3.1's system-cancel cascade ("refunded in full — wallet credit, punch restore, or both"). Two PRD-faithful readers diverge on the voluntary punch-only branch, so the assertion failed unique derivability. The scaffold rule that drove the generation was the compensating-invariant design tag assuming any restore flips session `payment_status`. The verbatim-covered assertions (session `CANCELLED`; participant `ACTIVE → REFUNDED` on punch restore, §3.4) were kept, and the amount>0 → `REFUNDED` rule remains covered by `test_full_refund_marks_session_cancelled_and_refunded`.

**Fixes applied to `test_helpers/`:** none.

**Fixes applied to `test_suite/`:** the one assertion removal above (plus docstring updated to document why `payment_status` is not asserted on the zero-money punch-restore branch).

**Fixes applied to `implementation/`:** none — the implementation's behavior (punch-only cancel with zero refunded amount leaves `payment_status` at `PAID`) is faithful to the literal §3.4 rule and no PRD-required check was weakened.

Orchestrator verification: all 8 `results.{1..8}.json` present; each round `passed=71, failed=0, errors=0, total=71`.

## Step 8: Finalize PRD — 2026-08-10T03:05:00.000Z

`PRD_FINALIZED.md` written at `/home/ubuntu/github/CodingPRD/tasks/task_0962_archery_range_lessons_proshop/workspace/PRD_FINALIZED.md`. The step_7_diff contained exactly one PRD-relevant item (the zero-money punch-restore cancellation branch); both edits trace to it. No other edits were warranted — no implementation fixes and no test_helper fixes were applied in Step 7.

## Line counts
- `PRD.md`: 331 lines; `PRD_FINALIZED.md`: 331 lines — 0% delta (two in-place sentence revisions, no lines added or removed).

## Changes
- §3.1 — revise — replaced "the session's `payment_status` becomes `REFUNDED` whenever any refund occurred" with an explicit deferral to the §3.4 rule (`REFUNDED` only when `cancellation_refund_cents` > 0), removing the reading under which a punch-restore-only system cancel flips `payment_status` — `implementation/app.py:346-347` (rule), `app.py:520` (suspension cascade calls the same `cancel_session(system=True)`).
- §3.4 — revise — pinned that `cancellation_refund_cents` totals wallet money only (punch restores contribute nothing), and that `payment_status` becomes `REFUNDED` if and only if that amount is greater than zero, so a zero-amount (e.g. punch-only) cancellation leaves `payment_status` unchanged — `implementation/app.py:309,327,331-343,345-347`.

## Per-edit pre-edit search log

**Edit 1 (§3.1)**
- (a) Subject: session `payment_status` transition to `REFUNDED` on system-cancel (suspension cascade).
- (b) Paths enumerated: all `payment_status` writes in `app.py` — session creation `UNPAID` (line 769), add-participant `PAID` (line 870), close `PAID` (line 958), `cancel_session` `REFUNDED`-iff-`total_refund > 0` (lines 346-347) shared by the voluntary route (`cancel_session_route`, lines 964-972, `system=False`) and the suspension cascade (`add_strike`, line 520, `system=True`); `no_show_session` (lines 352-359) never touches `payment_status`. Also checked the §3.3 parallel-status sentence ("`CANCELLED` or `NO_SHOW` sessions that issued refunds show `REFUNDED`") for consistency.
- (c) Adjustment: instead of asserting `REFUNDED` directly, the wording defers to the §3.4 amount>0 rule, because the suspension cascade runs the identical code path as voluntary cancel — a punch-only system-cancelled session has `total_refund == 0` and keeps `payment_status` at `PAID`, so any wording keyed to "any refund occurred" (including punch restores) would mis-describe that path.

**Edit 2 (§3.4)**
- (a) Subject: composition of `cancellation_refund_cents` and the exact trigger for the `payment_status` → `REFUNDED` transition on cancellation.
- (b) Paths enumerated: `cancel_session` wallet branch (lines 314-330 — only wallet refunds accumulate into `total_refund`, line 327) and punch branch (lines 331-343 — restore/reactivation with no accumulation); the assignment `session["cancellation_refund_cents"] = total_refund` (line 345) and the guard `if total_refund > 0` (line 346); both callers (voluntary route line 972; suspension cascade line 520); non-cancel `payment_status` writers (lines 769, 870, 958) to confirm `REFUNDED` is reachable only through this guard, making "if and only if" accurate; zero-participant and punch-only sessions to confirm `payment_status` is left untouched (could be `UNPAID` or `PAID`), hence "leaves `payment_status` unchanged" rather than "stays `PAID`".
- (c) Adjustment: deliberately chose "leaves `payment_status` unchanged" (under-determined about the prior value) instead of naming `PAID`, since a session cancelled before any participant was added remains `UNPAID`; and scoped the money-only claim to `cancellation_refund_cents` rather than redefining "refund" globally, keeping §3.3's "sessions that issued refunds" sentence and §3.1's "refunded in full — wallet credit, punch restore, or both" participant-level wording intact and un-contradicted.

## Step 9: Complete PRD — 2026-08-10T03:10:30.000Z

All edits applied cleanly — same line count, in-paragraph changes only. Final summary:

## PRD_COMPLETED.md produced

- **Source**: `PRD_FINALIZED.md` (331 lines, 49,899 chars) → `PRD_COMPLETED.md` (331 lines, 53,454 chars; **+3,555 chars**, zero line-count change — all edits are in-paragraph).
- **Counts**: 20 ambiguity-pins, 3 mismatch-revisions (23 edited passages total).

### Mismatch revisions (3)
- **§3.1** — revise — mismatch — `is_minor` is never stored at registration; it is derived against the current logical clock on every read and every check — `implementation/app.py:223-231` (`pub_member` recomputes per read).
- **§3.4** — revise — mismatch — cancelling a `CLOSED` session surfaces `ERR_SESSION_ALREADY_CLOSED`, not `ERR_SESSION_NOT_BOOKED` as "any other state" implied — `app.py:900-903, 970-972`.
- **§4** — revise — mismatch — recording a safety strike and posting a wallet adjustment return HTTP 201 despite creating no resource (PRD said modifications return 200) — `app.py:525, 550`.

### Ambiguity pins (20)
- **§2.3** — insert — ambiguity — non-integer limit/offset fall back to defaults; out-of-range values clamped, not rejected; sort ties broken by creation order — `app.py:198-205, 485-493`.
- **§2.4** — revise — ambiguity — `version` starts at 1 — `app.py:108`.
- **§2.7** — insert — ambiguity — version check fires after state-machine precondition, before availability checks — `app.py:1656-1661, 1920-1925`.
- **§2.8** — insert — ambiguity — `ERR_MEMBER_SUSPENDED` fires first within the waiver-and-consent gate — `app.py:247-249` (invoked before `require_active_waiver` at every gated site).
- **§3.1** — insert — ambiguity — `guardian_id` naming a nonexistent member → `ERR_MEMBER_NOT_FOUND` — `app.py:447-450`.
- **§3.1** — insert — ambiguity — strike `reason` accepted but not persisted; striking a non-`ACTIVE` member → `ERR_MEMBER_SUSPENDED` — `app.py:507-512`.
- **§3.2** — insert — ambiguity — adult signing another adult's waiver → `ERR_UNAUTHORIZED` — `app.py:566-570`.
- **§3.2** — insert — ambiguity — a `Member` may list their own waivers or those of a member they guard — `app.py:586-587`.
- **§3.3** — insert — ambiguity — `created_for_member_id` mandatory for `RangeOfficer` (else `ERR_INVALID_REQUEST`); `Member` booking for another → `ERR_UNAUTHORIZED`; unknown creator → `ERR_MEMBER_NOT_FOUND` — `app.py:716-729`.
- **§3.3** — insert — ambiguity — `booked_minutes` truncates fractional minutes — `app.py:760`.
- **§3.3** — insert — ambiguity — add-participant on `CLOSED` → `ERR_SESSION_ALREADY_CLOSED`; duplicate member (any participant status) → `ERR_INVALID_REQUEST`, evaluated after state and waiver gates — `app.py:826-835`.
- **§3.3** — insert — ambiguity — `Member` may read a participant record only for own participation or a session they created — `app.py:892-896`.
- **§3.3** — insert — ambiguity — check-in with no `ACTIVE` participants → `ERR_INVALID_REQUEST` — `app.py:912-915`.
- **§3.3** — insert — ambiguity — close from `BOOKED` → `ERR_SESSION_NOT_BOOKED`, from `CLOSED` → `ERR_SESSION_ALREADY_CLOSED`, early clock → `ERR_BOOKING_WINDOW_VIOLATION`; no insufficient-funds check during close reconciliation (balance may go negative) — `app.py:935-955`.
- **§3.5** — insert — ambiguity — `Member` may purchase punch cards only for themselves (path member = caller) — `app.py:609-611`.
- **§3.6** — insert — ambiguity — `Member` rents only for self; supplied `session_id` must exist (`ERR_SESSION_NOT_FOUND`) — `app.py:1027-1031`.
- **§3.7** — insert — ambiguity — deactivate/activate from the wrong state → `ERR_INVALID_REQUEST` — `app.py:1189-1190, 1200-1201`.
- **§3.8** — insert — ambiguity — duplicate-entry check counts entries of any status, including `CANCELLED` — `app.py:1442-1444`.
- **§3.8** — insert — ambiguity — scorecard submit from wrong league/entry state → `ERR_LEAGUE_NOT_OPEN`; verify/dispute/lock from wrong non-`LOCKED` states → `ERR_SCORECARD_NOT_EDITABLE`; verify gated on parent entry `CONFIRMED` → `ERR_LEAGUE_NOT_OPEN`; lock on `LOCKED` also → `ERR_SCORECARD_LOCKED` — `app.py:1609-1611, 1672-1710`.
- **§3.8** — insert — ambiguity — league cancel from `COMPLETED`/`CANCELLED` → `ERR_LEAGUE_NOT_OPEN`; standings exclude entries with no locked cards, computable in any league status, invalid `variant` → `ERR_INVALID_REQUEST`, row fields = `league_entry_id`, `member_id`, `total_points`, `x_hits`, `handicap_index`, `adjusted_points`, 1-based `rank` (computed fields present in `SCRATCH` rows too) — `app.py:1519-1521, 1541-1576`.
- **§3.9** — insert — ambiguity — sale `member_id` naming no member → `ERR_MEMBER_NOT_FOUND`; repair intake `member_id` likewise — `app.py:1768-1769, 1848-1849`.
- **§3.9** — insert — ambiguity — re-quote from `QUOTED` releases previously reserved parts to stock before validating/reserving the new set — `app.py:1926-1936`.

No new sections added; everything impl exhibits that PRD already pinned uniquely was left untouched.
