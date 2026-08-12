# Worklog — task_1245_jet_card_block_hour_program

## Step 1: Create Task Directory — 2026-08-12T00:00:00.000Z

Pre-assigned output folder `tasks/task_1245_jet_card_block_hour_program` with `workspace/` subdirectory already exists. Step 1 auto-index scan skipped per instructions; directory treated as created.

## Step 2: Generate Scaffold — 2026-08-12T07:06:00.000Z

## Summary

**Files created (all non-trivial size, valid YAML, clean lint):**
- `/home/ubuntu/github/CodingPRD/tasks/task_1245_jet_card_block_hour_program/SCAFFOLD.yaml` — 61,610 bytes (1,376 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1245_jet_card_block_hour_program/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 71,662 bytes (1,729 lines)
- `/home/ubuntu/github/CodingPRD/tasks/task_1245_jet_card_block_hour_program/SCAFFOLD_CORNER_DESIGN.yaml` — 58,201 bytes (1,441 lines)

**Lint verification:** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.`

**Key constraint check:** SCAFFOLD.yaml does NOT contain `scaffold_difficulty_design` or `scaffold_corner_design` keys (verified via Python parse and grep).

**§1.1–§1.7 counts (SCAFFOLD.yaml):**
- Entities: 13 (CardProgram, Member, JetCard, HourBankLedger, Aircraft, TripRequest, TripLeg, Invoice, PeakCalendar, BlackoutWindow, EscrowAccount, Refund, FractionalUpgrade)
- State machines: 4 (JetCard cyclic with SUSPENDED↔ACTIVE; TripRequest branching with DENIED/NO_SHOW; Refund with SUBMITTED→APPROVED→SETTLED cascade; Invoice with fork-join via DISPUTED)
- Calculations: 8 (billable_hours_per_leg, debited_hours_per_leg [3 variants], invoice_total [4 variants], hour_bank_reconciliation [chrono vs forward], escrow_release_on_completion, refund_net_amount, fractional_upgrade_credit, quoted_hours_estimate)
- Validations: 18 (priority-ordered across auth/existence/state/business_safety/temporal/constraint/fiscal/referential)
- Endpoints: 59 (including 13 FK reverse-reachability GETs, ops-run sweep, and /_clock/set_current_utc test-driver)
- Errors: 19
- Roles: 3 (Ops opaque, Member entity_backed:Member, Anonymous opaque)
- Concurrency rules: 2 (OCC on JetCard.version for refund-create and fractional-upgrade-create)

**§1.8 Difficulty Design (harder-than-expert):**
- 9 rule blocks × 2 instances each = 18 instances total
- Every instance has structured setup_api_calls with placeholder closure, trigger calls, and literal-computed asserts (e.g., `r4_net == 8000000`, `billable_minutes == 60`, `t3_peak == round_half_up(t3_sub * 0.15, 0)`)

**§1.9 Corner Design:**
- 9 sections (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting_layers, consistency_model)
- 24 instances covering creation/defaults/not-found/computed fields, invalid transitions/terminal lockdown/initial state/side-effect execution, calculation correctness, validation violations, standard CRUD/conditional actions, RBAC denial, OCC stale-version, cascading chain, derived-field reconciliation, and immediate consistency.

**Harder-than-expert calibration levers used:**
- Pricing-engine + ledger-reconciliation archetype blend (not pure CRUD)
- 5 cross-cutting complexity layers (OCC, dual-variant calc, cascading side effects, rate/threshold triggers, derived-field reconciliation)
- Cyclic + branching state machines on 4 different entities
- Depth-4 transitive cascade on trip completion (TripRequest → TripLeg → HourBankLedger → Card → Escrow → Invoice → Aircraft)
- Dual-variant calculations on 2 distinct domains (hour-bank ledger; invoice pricing)
- 4 invoice variants driven by (trip_kind × is_peak_period) — combinatorial formula with nested conditional and pre-pinned rounding order
- 2 OCC concurrency rules (refund, fractional upgrade) on JetCard.version
- Boundary-precision tests at min_billable_minutes floor (≥ vs >) and hours_remaining exact-equality

(Orchestrator note: the first Step-2 subagent turn was cut off before writing files; it was resumed via SendMessage and completed the full generation + lint. All three files verified on disk and YAML-parse cleanly.)

## Step 3: Copy Shared Files — 2026-08-12T07:13:00.000Z

Copied ./INSTRUCTION.md → tasks/task_1245_jet_card_block_hour_program/workspace/INSTRUCTION.md (1424 bytes).

## Step 4: Generate PRD — 2026-08-12T07:20:00.000Z

## Completion Summary

**File:** `/home/ubuntu/github/CodingPRD/tasks/task_1245_jet_card_block_hour_program/workspace/PRD.md`
**Size:** 40,183 bytes (305 lines)

### Structure
- §1 Introduction (2 paragraphs, business-context angle)
- §2 Global Specifications — 11 subsections: 2.1 RBAC, 2.2 Response Structure (verbatim), 2.3 Pagination, 2.4 Common Resource Properties, 2.5 Nested Resource Retrieval, 2.6 Money/Hours/Rounding, 2.7 OCC, 2.8 Hour Bank Ledger, 2.9 Escrow Custody, 2.10 Logical Clock & Sweeps, 2.11 Validation Ordering
- §3 Business Logic — 11 subsections organized by lifecycle: program setup, membership/fleet, card purchase/activation, quoting, confirmation, dispatch, completion, invoicing, expiration/closure, refunds, fractional upgrades
- §4 Endpoint table — 4 columns (Method, Path, Description, Authorized Role(s)), 59 endpoints
- §5 Error catalogue — 2 columns (Error ID, HTTP Status), 19 errors

### Hard Contract Audits

```
Field coverage check:
- entities[].fields + endpoints inputs + path_params + limit/offset: 102 required, 102 present, 0 missing
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 364
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Rule coverage spot-audit (Contract 2): all 18 validation rules mapped to error IDs in §2.11/§3 prose; both OCC rules (`expected_card_version` on refund + fractional-upgrade creation) expressed with `ERR_STALE_VERSION`/HTTP 412; all state-machine transitions (JetCard 6, TripRequest 8, Refund 4, Invoice 5) expressed with from/to states and side effects; all 8 calculations rendered as precise business prose with no pseudocode and no fuzzy wording; all 19 error IDs present; all enum values and role names verbatim. Status: PASS.

## Step 5: Generate Unit Tests — 2026-08-12T07:40:00.000Z

Generation complete and verified on disk.

**File inventory (all py_compile-clean):**

test_helpers/ (9 files, 37.8 KB total):
- `__init__.py` (897 B) barrel export — framework generics + PRD-specific
- `types.py` (6.6 KB) — 13 entity TypedDicts (HourBankLedger correctly carries only `id`+`created_at`), 13 status/role enums
- `api_client.py` (6.9 KB) — `ApiClient(GenericApiClient)` with 40 endpoint methods
- `api_errors.py` (2.2 KB) — 19 `ApiErrorId` values + HTTP map registered via `set_error_http_status_map`
- `assertions.py` (7.5 KB) — per-entity assertions + `assert_hour_bank_conservation` / `assert_escrow_conservation`
- `factories.py` (2.4 KB), `constants.py` (1.2 KB), `test_users.py` (957 B, opaque Ops/Anonymous constants + `make_member_headers` entity-backed builder), `fixtures.py` (8.2 KB, 5 tiers incl. `setup_active_card`, `fly_trip`, `complete_trip`, OCC refund helpers, `expire_card_via_sweep`)

test_suite/ (10 files, 65.5 KB total): `conftest.py` + `test_01`…`test_09` grouped by concern (setup, RBAC/errors, card lifecycle, trip confirmation, dispatch, completion billing, invoices, refunds, expiration/invariants).

**Queue results:**
- Queue A (Difficulty): **17/18 instances emitted, 34 tests** (≥2 each). **1 skipped:** `boundary_precision_check/insufficient_hours_at_exact_remaining` — its asserted outcome (confirm succeeds at exactly `hours_remaining == 1.00`) requires `quoted_hours == 1.00` for the KTEB→KPBI pair, but `quoted_hours` derives from a server-side airport coordinate table the PRD explicitly does not expose, so no PRD-only reader can derive the boundary outcome. Gap left as a gap (no placeholder, no skip marker).
- Queue B (Corner): **24/24 non-stub instances emitted, 24 tests**; no `excluded_because:` stubs exist in this index.

**Tag audit:** 58/58 tests carry exactly one `Design:` line; every tag resolves to a real instance name in the source YAMLs; zero untagged/dual-tagged/dangling tests. **Citation audit:** every test docstring contains a ≥6-word quoted sentence verified verbatim against PRD.md (grep-normalized); elided citations from the first pass were rewritten to full verbatim sentences. No `pytest.mark.skip`/`skipif`/`xfail` anywhere.

Notable adjudications: the escrow-conservation instance's literal `available_cents == 0` assert contradicts PRD §3.10 (only `net_refund_cents` leaves escrow at settle; the 20% penalty = 1,600,000 cents remains), so the tests assert the PRD-derived values (`available == 1,600,000`, `released == 8,400,000`) plus the conservation invariant `principal == available + released + forfeited`, which holds.

## Step 6: Generate Implementation — 2026-08-12T07:44:00.000Z

Completion summary.

**Implementation generated** at `/home/ubuntu/github/CodingPRD/tasks/task_1245_jet_card_block_hour_program/workspace/implementation/` — Python + Flask, in-memory only, no startup seeding (store starts empty; logical clock initializes to 2026-05-01T00:00:00Z per PRD §2.10).

**File inventory (16 files, ~87 KB):**
- `start.sh` (396 B, executable) — guarded Flask install (`if ! python3 -c "import flask"`), `exec python3 app.py`, foreground
- `requirements.txt` (16 B) — flask>=3.0,<4.0
- `app.py` (1,367 B) — app factory, blueprint registration, ApiError/404/405/500 envelope handlers, `0.0.0.0:$PORT` (default 10000)
- `store.py` (1,206 B) — empty in-memory tables + logical clock + insertion sequence
- `util.py` (8,681 B) — ISO-8601 ms timestamps, Decimal half-up helpers (hours 2dp / money 0dp), add_months, haversine NM distance with fixed ICAO coordinate table + deterministic hash fallback
- `httpkit.py` (8,648 B) — envelope (`meta`/`response_type`/`data`, `error_id`/`message`), auth (`X-User-Role`/`X-User-ID`, Member requires ID), role gates, member-ownership 403s, strict body schema validation (400 first per PRD §2.11), pagination (`limit`/`offset`, 10/1/100/0)
- `serializers.py` (6,732 B) — all 12 entity serializers; HourBankLedger omits `updated_at`/`version` per PRD §2.4
- `services.py` (11,703 B) — version/touch bookkeeping, ledger insertion, chrono/forward hour variants, quoting, peak/blackout checks, activation cascade, per-leg billing + swap multiplier, invoice math, completion cascade, expiration sweep
- `routes_programs.py` (6,610 B), `routes_members.py` (2,386 B), `routes_cards.py` (11,778 B), `routes_aircraft.py` (2,929 B), `routes_trips.py` (16,944 B), `routes_invoices.py` (2,089 B), `routes_refunds.py` (4,900 B), `routes_ops.py` (1,151 B)

**Route audit: EXACT MATCH 59/59** — scaffold endpoints extracted programmatically from SCAFFOLD.yaml and diffed against `app.url_map`; zero missing, zero extra.

**Boot smoke test: PASS** — `PORT=<free> bash start.sh &` (also via setsid), HTTP ready in <3 s, `GET /programs` as Anonymous → 200 with correct empty-list envelope; process killed cleanly. Fresh-restart verified: state is empty after kill+relaunch (per-test-server isolation safe).

**Functional verification (beyond the mandatory checks):** ~50 end-to-end assertions run against a live server, all passing — activation cascade (grant + escrow + expires_at +18mo), quote floor/round-trip doubling, confirm → dispatch → depart → complete with exact decimal math (subtotal/surcharge/discount at each step), swap downgrade (×0.85), invoice DRAFT→ISSUED at v2, OCC 412 on refunds/upgrades + card-version bump on create, refund penalty math (20% < 12mo) and settle cascade to REFUNDED, expiration sweep (EXPIRED + forfeiture; forward projection pinned at expires_at), blackout/insufficient-hours denials (trip → DENIED with reason AND error surfaced), SLA/pax/open-trips guards, RBAC 401/403s, pagination validation, FK reverse reads.

One ambiguity note: `denial_reason` for confirm failures due to card-not-active / member-not-active is not representable in the scaffold's 4-value enum; I map hours→INSUFFICIENT_HOURS, blackout→BLACKOUT, card→AVAILABILITY_WINDOW, member→PEAK_RESTRICTED, and the trip still transitions to DENIED per PRD §3.5 in all four cases.

## Step 7: Run Tests and Iterate — 2026-08-12T07:58:00.000Z

All 8 rounds pass 57/57. Clean sweep achieved.

## Summary

- **Iterations run:** 3 eight-round parallel sweeps. Sweep 1: 58/58 collection failure (2 files). Sweep 2: 56/58 in all rounds (3 root causes). Sweep 3: 57/57 × 8 rounds — clean, exit.

- **Tests deleted (1):**
  - `test_confirm_rejection_leaves_trip_in_quote` (test_suite/test_04_trip_confirmation.py) — BRANCH-ASYMMETRIC SIDE EFFECT / unique-derivability collapse. PRD §3.5 says "When any precondition fails, the trip … transitions from `QUOTE` to `DENIED`" and lists card-active among the four preconditions, yet the `denial_reason` enum (`INSUFFICIENT_HOURS`, `BLACKOUT`, `AVAILABILITY_WINDOW`, `PEAK_RESTRICTED`) has no class for a card-not-active failure. Two faithful PRD-only implementations diverge (DENIED with a best-effort reason vs. remain in QUOTE). The PRD-covered half of the scenario (surfacing `ERR_CARD_NOT_ACTIVE`, 409) remains covered by `test_confirm_on_suspended_card_rejected` and `test_confirm_suspended_card_yields_card_not_active`. Scaffold driver: Difficulty/cross_entity_state_dependency/trip_confirm_requires_card_active.

- **Fixes applied to `test_helpers/`:**
  - `fixtures.py` — added missing `get_aircraft()` fixture (wraps existing `api_client.get_aircraft`); its absence caused collection failure of test_05/test_06. The helper reads `GET /aircraft/{aircraftId}`, a PRD §3.2/§4 endpoint, used to assert PRD-mandated aircraft status transitions.
  - `fixtures.py` — `complete_trip()` leg payload field changed from `trip_leg_id` to `leg_seq`; PRD §3.6 names `leg_seq` as the leg identifier and §3.7 requires only each leg's `actual_block_minutes`.
  - Global clock remediation across `test_helpers/` and `test_suite/` — every date literal shifted +5 months (earliest now 2026-06-01). PRD §2.10 initializes the logical clock at 2026-05-01T00:00:00Z and states "Time only moves forward"; fixtures previously set the clock to 2026-01-01, which a PRD-faithful server must reject. Uniform shift preserves all relative offsets (expiry, penalty anniversary, peak/blackout containment).

- **Fixes applied to `implementation/`:**
  - `util.py::new_uuid` — return `str(uuid.uuid4())` (canonical dashed form) instead of `uuid4().hex`; PRD §2.4 requires a "server-minted UUID with no type prefix".
  - `services.py::insert_ledger_entry` / `run_expiration_sweep` — added `effective_at` override; the `EXPIRATION_DEBIT` now takes effect at the card's `expires_at` (the moment hours lapse) instead of sweep time, so the PRD §2.8 forward-looking variant (entries with `effective_at` ≤ min(now, `expires_at`)) genuinely "forecast[s] the post-expiry floor" of 0 after the sweep.

(Orchestrator disk verification: all 8 results.{1..8}.json present; every round passed=57 failed=0 total=57 errors=0.)

## Step 8: Finalize PRD — 2026-08-12T08:05:00.000Z

All edits applied and verified against the diff. Summary follows.

## Summary

**Line counts:** PRD.md = 305 lines; PRD_FINALIZED.md = 305 lines; 0% line-count delta (4 inline revisions, no sections added or removed).

**Changes (one per bullet):**
- §2.4 — revise — pinned the resource `id` to a server-minted UUID "rendered in its canonical dashed string form" (was just "a server-minted UUID with no type prefix", which also admits the 32-char hex form) — `implementation/util.py:54-55` (`new_uuid` returns `str(uuid.uuid4())`).
- §3.5 — insert — added the explicit precondition-to-`denial_reason` mapping for failed trip confirmation: card-not-ACTIVE → `AVAILABILITY_WINDOW`, member-not-ACTIVE → `PEAK_RESTRICTED`, blackout → `BLACKOUT`, insufficient hours → `INSUFFICIENT_HOURS` (the deleted `test_confirm_rejection_leaves_trip_in_quote` site; PRD previously left the card/member failure classes undetermined) — `implementation/routes_trips.py:228-247` (`_deny_trip` calls in `confirm_trip`).
- §3.7 — revise — pinned the completion `legs` payload shape: one entry per leg, identified by `leg_seq` (leg `id` accepted as alternative) plus `actual_block_minutes` (was just "the `legs` payload with each leg's `actual_block_minutes`") — `implementation/routes_trips.py:337-378` (`complete_trip_endpoint`).
- §3.9 — revise — pinned the `EXPIRATION_DEBIT` entry's `effective_at` to the card's `expires_at` (moment hours lapse) rather than sweep time, making §2.8's forward-looking "post-expiry floor" forecast genuinely hold — `implementation/services.py:326-327` (`run_expiration_sweep` → `insert_ledger_entry(..., effective_at=card["expires_at"])`).

**Step-7 items needing no PRD edit:** the `get_aircraft()` fixture addition and the global +5-month clock shift were pure fixture bugs — PRD §4 already documents `GET /aircraft/{aircraftId}` and §2.10 already pins clock init at 2026-05-01T00:00:00Z with forward-only movement.

**Per-edit pre-edit search log:**
1. **UUID format** — (a) subject: resource `id` minting. (b) Enumerated: `util.py:54-55` (`new_uuid`), all call sites via `services.py:26-34` (`new_common`) and `services.py:37-51` (`insert_ledger_entry`) — covers every persisted resource; `serializers.py` passes `id` through unmodified. (c) Wording scoped to the dashed string rendering only; no claim about version/variant bits, so all call sites remain accurately described.
2. **Confirm denial mapping** — (a) subject: trip `DENIED` transition + `denial_reason` on confirm. (b) Enumerated: `routes_trips.py:40-44` (`_deny_trip`, only writer of trip `DENIED`), its four call sites at lines 229/233/240/245, `create_trip` (sets `denial_reason` null, line 103), `cancel_trip` (no denial_reason touch), `serializers.py:109` (read-only), and `routes_refunds.py:98-106` (separate `Refund.denial_reason`, operator free-text — explicitly out of scope of my sentence). (c) Wording scoped to "the four preconditions" of confirmation only, so the refund denial path is not implicated; the mapping sentence asserts exactly the impl's four pairs and nothing more (no claim about guard ordering beyond what §2.11/§3.5 already pin).
3. **Completion legs payload** — (a) subject: how completion payload entries identify legs. (b) Enumerated: `routes_trips.py:321-383` is the sole consumer of a `legs` payload (accepted keys `leg_seq`, `id`, `actual_block_minutes`; unknown keys → `ERR_INVALID_REQUEST`; all legs required); `services.py:179-215` (`create_trip_legs`) defines `leg_seq` 1/2; no other endpoint takes leg identifiers in a body. (c) Mentioned both `leg_seq` and the `id` alternative so the wording does not narrow the impl's accepted input; did not pin the rejection error code (impl uses `ERR_INVALID_REQUEST` after the state guard, and §2.11's schema-validation clause already covers malformed payloads).
4. **EXPIRATION_DEBIT effective_at** — (a) subject: ledger entry `effective_at` values. (b) Enumerated all `insert_ledger_entry` call sites: `services.py:152` (PURCHASE_GRANT), `services.py:278` and `routes_trips.py:440` (TRIP_DEBIT), `routes_refunds.py:126` (REFUND_DEBIT), `routes_cards.py:270` (UPGRADE_DEBIT) — all default `effective_at` to now; only `services.py:326-327` overrides. Consumers `chrono_hours_remaining` / `forward_hours_remaining` (services.py:58-78) and the §2.8 forward-variant prose re-checked for consistency. (c) Wording pins only the `EXPIRATION_DEBIT` stamp and is silent on other entry kinds, leaving their `effective_at` under-determined as before — no false universal claim introduced.

## Step 9: Complete PRD — 2026-08-12T08:16:00.000Z

## Summary

**Source:** `PRD_FINALIZED.md` (305 lines / 40,843 chars) → `PRD_COMPLETED.md` (306 lines / 44,263 chars); char-delta **+3,420**. Only inline inserts/revisions; no new sections.

**Counts:** 20 ambiguity-pins, 5 mismatch-revisions (25 total change bullets below; some edits combine one pin + one revision).

- §2.1 — insert — ambiguity — only `Member` requires `X-User-ID`; `Ops`/`Anonymous` may omit it — httpkit.py:111-119
- §2.1 — insert — ambiguity — Member callers on non-member-parent collections (program's jet cards, aircraft's trip requests) get filtered own-subset, not 403 — routes_programs.py:156-157, routes_aircraft.py:85-87
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from the wall clock, not the logical clock — httpkit.py:69, util.py:49-51
- §2.3 — insert — ambiguity — invalid `limit`/`offset` (non-integer, out of 1–100, negative offset) → `ERR_INVALID_REQUEST` (400); `created_at` ties broken by insertion order — httpkit.py:231-264
- §2.5 — insert — ambiguity — undefined paths and unsupported methods surface as `ERR_NOT_FOUND` (404) — app.py:32-40
- §2.8 — insert — ambiguity — ledger `effective_at` defaults to current logical time when unspecified — services.py:46
- §2.8 — insert — ambiguity — projection read returns the full card object with `hours_remaining` reporting the forward-looking variant — routes_cards.py:152-159
- §2.10 — insert — ambiguity — clock-set to a past instant → `ERR_INVALID_REQUEST` (400), equal instant allowed, response carries `current_utc` — routes_ops.py:31-42
- §2.10 — insert — ambiguity — sweep response object: `expired_card_ids`, `closed_card_ids`, `expired_count`, `closed_count`, `current_utc` — routes_ops.py:16-28
- §2.11 — revise — ambiguity — schema validation explicitly includes rejection of any unrecognized body field — httpkit.py:186-189
- §3.1 — insert — ambiguity — duplicate `program_code` → `ERR_INVALID_REQUEST` (400); category tiers rank LIGHT < MIDSIZE < SUPER_MID < HEAVY for swap direction — routes_programs.py:48-50, util.py:210-217
- §3.2 — insert — ambiguity — duplicate member `email` → `ERR_INVALID_REQUEST` (400); member suspension has no from-state guard — routes_members.py:36-38, 60-68
- §3.2 — insert — ambiguity — duplicate `tail_number` → `ERR_INVALID_REQUEST` (400) — routes_aircraft.py:36-38
- §3.3 — insert — ambiguity — pre-activation card: `purchased_at`/`expires_at` null, all hour counters and `escrow_balance_cents` zero — routes_cards.py:64-77
- §3.3 — insert — ambiguity — `expires_at` uses calendar-month addition with day clamped to target month length — util.py:58-64
- §3.4 — insert — ambiguity — round-trip missing `requested_return_utc` → `ERR_INVALID_REQUEST` (400); supplied value on one-way is discarded — routes_trips.py:73-82, 96-97
- §3.4 — insert — ambiguity — quote floor is min-billable minutes converted to hours and rounded half-up to 2dp; coordinates from fixed table with deterministic fallback — services.py:109-116, util.py:185-194
- §3.5 — insert — ambiguity — confirming a non-`QUOTE` trip → `ERR_INVALID_STATE` (409) with no denial transition — routes_trips.py:223-224
- §3.6 — revise — ambiguity — SLA guard rejects only dispatch more than `availability_window_hours` *after* requested departure; early dispatch always satisfies it — routes_trips.py:276-283
- §3.6 — revise — mismatch — fleet guard checks only that the *chosen* aircraft is `AVAILABLE`; no category-compatibility restriction (category difference merely sets `swap_applied`) — routes_trips.py:284-295
- §3.6 — revise — mismatch — deleted server-side eligibility/ranking and repositioning-cost prose; operator picks aircraft explicitly, `reposition_rate_cents_per_nm` enters no billing computation — (no impl counterpart)
- §3.6 — insert — ambiguity — Member cancel of `DISPATCHED` → `ERR_UNAUTHORIZED` (403); cancel from any status other than `QUOTE`/`CONFIRMED`/`DISPATCHED` → `ERR_INVALID_STATE` (409) — routes_trips.py:396-419
- §3.6 — revise — ambiguity — no-show debit is one per-leg minimum times the dispatched-category swap multiplier, independent of `trip_kind` — routes_trips.py:436-440
- §3.7 — insert — ambiguity — completion `legs` payload schema pinned: non-negative integer `actual_block_minutes`; unknown fields, unmatched/duplicate/missing legs → `ERR_INVALID_REQUEST` (400) — routes_trips.py:321-378
- §3.11 — revise — mismatch — conversion value de-named as a persisted field (computed only for the 1/16 threshold); `APPLIED`/`CANCELED` exist in the enumeration only — upgrade stays `PENDING` with `applied_at` null, no apply/cancel endpoint — routes_cards.py:250-273, serializers.py:201-210
- §4 — insert — ambiguity — action endpoints without a request schema reject a non-empty body with `ERR_INVALID_REQUEST` (400) — httpkit.py:207-218
- §5 — insert — ambiguity — added `ERR_INTERNAL` (500) row for unexpected server errors — app.py:42-44
