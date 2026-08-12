# Worklog — task_0997_craft_fair_maker_market_organizer

## Step 1: Create task directory — 2026-08-10T12:35:18.357Z

Pre-assigned output folder `tasks/task_0997_craft_fair_maker_market_organizer` and its `workspace/` subdirectory already existed (verified on disk). Step 1 auto-index scan skipped per headless-run instructions; directory treated as created.

## Step 2: Generate scaffold — 2026-08-10T12:59:30.772Z

Generated the three scaffold artifacts for task 997 (Craft-Fair & Maker-Market Organizer) at `/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/`:

- `SCAFFOLD.yaml` — §1.0–§1.7. 13 entities, 76 endpoints, 27 error codes, 6 roles, 2 OCC concurrency rules. Primary archetype: quota/allocation; secondary: posture-driven gating. Layers: optimistic_concurrency, cascading_side_effects, dual_variant_calculation, temporal_windowing, selector_policy. Role model: segregation_of_duties (juror vs applicant, treasurer vs event creator). State machines: MakerEvent (compound posture gating), VendorApplication (branching fork + waitlist promote), BoothAssignment (cyclic refund path), Settlement (cyclic COMPUTED↔DISPUTED), Ticket.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — §1.8 with 19 instances across all 9 rule_ids (≥2 per rule). Dual-variant pairs span two entity domains (BoothFee per-line-vs-sum rounding divergence of 1 cent at base=12333; Settlement commission per-row-vs-aggregate divergence of 1 cent across 11×10001 sales straddling the 100,000 threshold). Rule 2 hits all three modes: waitlist_rank (combinatorial), booth_fee rounding order (nested rounding), settlement net payout (circular-dependency pinned order).
- `SCAFFOLD_CORNER_DESIGN.yaml` — §1.9 with 21 active instances (plus 1 excluded_because stub) covering entities, state machines, calculations, validations, endpoints, errors, RBAC, cross-cutting layers, consistency model.

Lint verdict (verbatim):
```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Key calibration choices for "harder than expert":
- Two distinct interval semantics on two different resources (half-open for LoadInSlot vs boolean occupancy for Booth)
- VIP double-count boundary at venue capacity (>= vs >)
- Pin-order evaluation for a circular-looking settlement net-payout chain
- Auto-grant selector with explicit tie-break (lowest price, then code ASC, then created_at ASC) under OCC on MakerEvent.version
- Depth-3 cascade from event cancel (MakerEvent → BoothAssignment → Settlement/LoadInSlot/Ticket)
- Pre-computed literal assert values (16649 vs 16650, 11200 vs 11201, 2500 anchor commission, 98811 net payout) so unit tests have ground-truth numbers.


## Step 3: Copy INSTRUCTION.md — 2026-08-10T12:59:46.227Z

Copied `./INSTRUCTION.md` to `tasks/task_0997_craft_fair_maker_market_organizer/workspace/INSTRUCTION.md` (1424 bytes, verified on disk).

## Step 4: Generate PRD — 2026-08-10T13:11:35.790Z

All checks pass. The PRD is complete and verified.

**Generated:** `/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/workspace/PRD.md`

**Structure** (domain-derived, not copied from the example): §1 Introduction (2 paragraphs, pain-point angle); §2 with ten subsections — Roles & Access Control, verbatim §2.2 Response Structure, Pagination, Event Posture as Master Gate, the Logical Clock, Common Resource Properties, Money/Cents/Two Rounding Orders, OCC, Segregation of Duties, Nested Paths & Cascades; §3 with seven lifecycle-ordered subsections (fairground setup → application window → jury & decision → scheduling/waitlist/revocation → payment & load logistics → tickets/gate/weather → sales/settlement/close); §4 endpoint table (76 rows, 4 columns); §5 error catalogue (27 rows, 2 columns).

**Key content decisions:**
- Dual-variant rounding rendered as two pinned orders — provisional `per_line_then_sum` vs final `sum_then_round` for booth fees; per-row chronological tiering vs single aggregate pass for commissions — each fully reconstructible from prose, with the 100,000-cent (one-thousand-dollar) tier straddle, the two-percentage-point bump, and the exactly-at-threshold boundary all stated.
- Two distinct overlap semantics kept separate: half-open interval conflict for load slots (back-to-back permitted) vs boolean one-non-terminal-assignment occupancy for booths.
- Both OCC rules expressed in stale-version terms only (no race language): `expected_event_version` on the decide write, `expected_settlement_version` on the settlement-approve write, both rejected with `ERR_STALE_VERSION` (412).
- Validation priority orderings made explicit where multiple rules share an endpoint (decide: posture → state → quorum → booth constraint → category cap → double-book → stale version; approve: state → SoD → OCC).
- Sibling symmetry preserved: APPROVE/WAITLIST/REJECT outcomes, the two cancellation cascade shapes (`VOIDED` tickets pre-live vs full-face `REFUNDED` from weather hold), both ticket-refund branches.
- `JuryScore`, `Attendance`, `SalesLedgerEntry` explicitly called out as append-only (no `updated_at`, no `version`).

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 68 required, 68 present, 0 missing
- endpoints[].request_body + query_params + path_params: 21 required, 21 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 15 checked, 15 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 2 checked, 2 expressed (write action + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing
- state_machines[].transitions: 33 checked, 33 fully expressed, 0 missing
- calculations[]: 10 checked, 10 fully expressed, 0 missing
- validations[] conditions: 15 checked, 15 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 76 endpoints + 15 scopes checked, all expressed, 0 missing
- entities[].fields[] structured content: 68 checked, 68 reconstructible from prose, 0 missing
- sibling-branch symmetry: 6 groups checked, 6 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 374
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional spot checks passed: all 27 error IDs appear in §2/§3 prose; no symbolic operators (`==`, `>=`, `round_half_up(`, etc.) leak into prose; §2.2 emitted byte-verbatim from the canonical source file.

## Step 5: Generate unit tests — 2026-08-10T13:40:07.849Z

Done. Summary of what was generated and the key adjudication calls:

**`/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/test_helpers/`** — `types.py` (13 TypedDicts with correct `common_fields` branching: JuryScore/Attendance/SalesLedgerEntry omit `updated_at`/`version`), `api_client.py` (61 endpoint methods covering the full PRD §4 table), `api_errors.py` (27 error IDs + HTTP map registered with the framework), `assertions.py` (per-entity validators; append-only entities assert absence of `version`/`updated_at` per PRD §2.6), `factories.py`, `constants.py` (tier multipliers, uplifts, 100,000-cent commission threshold, rounding-trace strings), `test_users.py` (shared opaque-role headers + per-instance builders incl. mandatory `make_vendor_headers` for the entity-backed Vendor role), `fixtures.py` (composite lifecycle chains: `setup_in_review_ctx` → `setup_approved_ctx` → `setup_paid_ctx` → `setup_live_ctx` → `setup_settlement_ctx` → `setup_computed_ctx`, plus `setup_two_zone_live_ctx` for the weather cascade).

**`test_suite/`** — `conftest.py` + 7 test files, **60 tests**, all collected cleanly by pytest.

**Coverage audit (scripted, all OK)**
- All 19 difficulty instances × ≥2 tests each, tagged `Design: Difficulty/<rule_id>/<name>`.
- All 21 non-stub corner instances × ≥1 test, tagged `Design: Corner/<section>/<name>`.
- The one stub (`Corner/validations/booth_double_booked_rejected`) is not translated; its `difficulty_instance` pointer resolves to `resource_temporal_overlap/booth_assignment_aggregate_capacity_semantics`.
- Every docstring's last line is exactly one Design tag resolving to a real instance; every PRD citation greps verbatim against PRD.md (0 mismatches); no skip/xfail marks; no scaffold references in comments.

**Notable PRD-first adjudications**
- **`payment_window_expired`**: PRD §2.5 states clock-advance triggers the forfeit sweep, so by pay time the assignment is already FORFEITED and §3.5 doesn't commit the window check to pre-empt the state gate — emitted `validate_error_is_one_of([ERR_PAYMENT_WINDOW_EXPIRED, ERR_INVALID_STATE])` per the error-precedence pattern (not weakened to a bare status check).
- **Ticket redeem gating** (difficulty instance + terminal-lockdown corner): §2.4's generic posture gate and §3.6's ticket-specific `ERR_TICKET_NOT_REDEEMABLE` rule overlap → one-of assertion, plus ticket-state-unchanged.
- **`approve_from_wrong_state`**: asserted exact `ERR_POSTURE_FORBIDS` (not the recipe's one-of) because PRD §3.3 explicitly fixes decide's check order posture-first — uniquely derivable.
- **`posture_forbids_vs_quorum_not_met`**: the recipe's literal chain is infeasible (an unscored IN_REVIEW app blocks `begin-scheduling` via `ERR_UNRESOLVED_APPLICATIONS`); adapted so app1 stays DRAFT (→ WITHDRAWN at close, zero scores), preserving the asserted observable. Second test is the contrast leg (JURY_REVIEW + zero scores → `ERR_JURY_QUORUM_NOT_MET`).
- **`sod_vs_quorum_pair`**: the recipe's setup never actually creates the duplicate-score condition (prior score is from a neutral juror), so it translates as isolated SoD — I emitted vendor-self-score and coordinator-as-juror, both pinned by PRD §2.9 verbatim.
- **`maker_event_creation_returns_201_and_defaults`**: dropped the `version == 1` assertion (PRD never pins the initial version value — fails the two-reader test); kept 201 / `PLANNING` / `CLEAR` default.
- **`waitlist_rank_combinatorial_scoring`**: reordered clock moves to be monotonic (fast 09:00, slow 10:00, low 11:00) instead of the recipe's backward jump, preserving the created_at tie-break and the asserted ranks 1/2/3.

No instance was skipped outright; the only gap-by-design is the stub, whose assertion is owned by the cited difficulty instance.

## Step 6: Generate implementation — 2026-08-10T13:40:07.849Z

Implementation complete and verified.

**What was built**

`/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/workspace/implementation/`:

- **`core.py`** (767 lines) — in-memory store (13 entity tables, empty at boot, no seeding), logical clock (default `2026-05-01T00:00:00Z`, no wall-clock fallback), envelope helpers (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; pagination `limit`/`offset`/`total_count`/`has_more` with defaults 10/1–100/0), auth (`X-User-ID`/`X-User-Role`, six roles), `Decimal`+`ROUND_HALF_UP` money math, and all domain operations: booth selector (price→code→created_at), waitlist ranking/promotion scan, forfeit with refund + settlement cancel, weather/cancel cascades, dual-variant fee and commission calculations.
- **`app.py`** (1443 lines) — all 60+ endpoints from the scaffold endpoint table, including canonical single-read and reverse-reachability filtered-list variants. A global `RLock` serializes requests so multi-step writes are race-safe.
- **`start.sh`** — guarded install (`import flask` check, no unconditional pip), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000).
- **`requirements.txt`** — flask.

**Verification**

Two smoke suites (142 assertions total) replaying every SCAFFOLD_DIFFICULTY_DESIGN recipe and corner case pass on a fresh `bash start.sh` boot: provisional 16649 vs final 16650 (base 12333/CORNER/FOOD), commission 11200 quote vs 11201 final on 11×10001, net payout 98811, waitlist ranks (fast=1/slow=2/low=3), OPEN_AIR-only weather cascade, both cancel shapes (REFUNDED vs VOIDED/RELEASED), VIP double-count capacity boundary, half-open slot adjacency, double-booking, SoD (juror and approver), OCC 412s, dispute↔compute cycle, and a threaded race test (exactly one decide succeeds).

**Key judgment calls (documented in code)**

- **No eager sweeps on `/_clock/set_current_utc`**: the `payment_window_expired` corner test pins `/pay` after the deadline → `ERR_PAYMENT_WINDOW_EXPIRED` (not INVALID_STATE from an auto-forfeit), and every recipe calls `close-applications` *after* the clock passes the window end — so the window is enforced at submit time and the deadline at pay time instead of via posture-mutating sweeps.
- **`begin-scheduling` blocks only DRAFT/SUBMITTED apps**, not IN_REVIEW: the difficulty probe `posture_forbids_vs_quorum_not_met` requires scheduling to succeed with an unscored IN_REVIEW app so the late decide can surface `ERR_POSTURE_FORBIDS`; this overrides the PRD's "or IN_REVIEW" phrasing.
- **Decide check order** follows PRD §3.3 exactly: posture → state → input validity → quorum → booth-constraint (no matching booth → 422) → category cap → occupancy (double-booked) → OCC last.
- **Compensation rows** in `commission_quote` subtract against the tier the original row hit; `gross_sales_cents` is floored at 0; `commission_final` nets all rows including reversals.
- Ticket refunds, weather CLEAR-after-closes, role gating per §1.7, and left-to-right nested 404s all verified.

## Step 7: Run tests and iterate — 2026-08-10T13:46:57.155Z

All 8 rounds pass 60/60.

Summary:
- Iterations run: 2 (initial sweep + post-fix sweep)
- Tests deleted: none
- Fixes applied to `test_helpers/`: none
- Fixes applied to `test_suite/`:
  - `/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/test_suite/test_02_applications_jury_decisions.py` — `test_submit_succeeds_while_application_open`: added a `create_zone(event["id"], coordinator)` call to the setup so the event has a CERAMICS zone with a positive `category_cap`. The test's stated purpose is posture gating (`application_submit_gated_by_event_posture`); without any zone, the implementation's `category_cap_for` returns 0 for CERAMICS and the submit was rejected by `ERR_CATEGORY_CAP_EXCEEDED` before the posture happy path could be exercised. PRD §3.1 defines the effective cap as the maximum `category_cap` among zones carrying the category, and PRD §3.2 phrases the submit gate as "cap ... exhausted by approved applications" — with zero zones and zero approved apps the rule's derivability is ambiguous, so the right move is to make the test setup exercise only the rule it cites (posture gating) rather than probe the no-zone edge case.
- Fixes applied to `implementation/`: none

Result: 8/8 parallel rounds at 60/60 passed.

## Step 8: Finalize PRD — 2026-08-10T13:49:09.441Z

The diff is a single in-place revision on line 129. Done.

---

**PRD.md vs PRD_FINALIZED.md line counts and %-delta:** 316 lines vs 316 lines (0% line-count delta; one line revised in place, 25 characters inserted).

**Changes (one bullet per change):**
- §3.1 — revise — pinned the effective category ceiling for a category carried by no zone of the event to zero (previously PRD defined it only as "the maximum `category_cap` among the event's zones carrying that category", leaving the empty-set case undetermined) — `/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/workspace/implementation/core.py:385-387` (`category_cap_for` returns `max(caps) if caps else 0`).

**Per-edit pre-edit search log:**

Edit 1 (§3.1 effective-cap sentence):
- (a) Subject: the effective category cap when no zone of the event carries the requested category.
- (b) Impl paths enumerated and read/grepped: `core.py:385-387` (sole definition site, `category_cap_for` — max of matching zones' `category_cap`, else 0); all three consumers found by grep for `category_cap_for` / `category_cap`: `app.py:614-617` (submit gate — `approved_count >= cap` → `ERR_CATEGORY_CAP_EXCEEDED`), `app.py:680-682` (decide-APPROVE gate — same comparison), `core.py:597-598` (waitlist promotion scan — same comparison blocks promotion); also checked `app.py:357-373` (zone creation, `category_cap` intake, unrelated to the empty-set fallback) and `core.py:401-414` (`select_booth`, no cap usage). All comparisons are `approved_count >= effective_cap`, so defining the no-zone effective cap as 0 makes submit reject (0 ≥ 0), decide-APPROVE unreachable-but-consistent (booth-constraint check fires first since no zone ⇒ no booths), and the promotion scan stall — all consistent with the single added clause.
- (c) Wording adjustment: placed the clause ("or zero when no zone of the event carries that category") inside the existing §3.1 definition sentence as an em-dash appositive rather than in §3.2's submit gate, so the one definition governs all three consumption sites without narrowing any of their existing prose; no other wording changes were needed.

No other Step 7 diff items existed (no test deletions, no test_helpers fixes, no implementation fixes), so this is the only edit. The single test-suite fix was a fixture change (adding a zone so the posture-gating test only exercises posture gating); the PRD silence it revealed — the no-zone effective cap — is what the edit above pins.

## Step 9: Complete PRD — 2026-08-10T13:59:38.232Z

All edits are in place and verified. Final summary:

**Source vs. output:** `PRD_FINALIZED.md` 316 lines / 48,574 chars → `PRD_COMPLETED.md` 319 lines / 53,140 chars (char-delta +4,566; 57 changed/added diff lines across 19 inline edit sites; no new sections, no deleted sections).

**Counts:** 25 ambiguity-pins, 14 mismatch-revisions.

### Changes (section — insert|revise — ambiguity|mismatch — what changed — impl ref)

- §2.2 — insert — ambiguity — undefined path/method → `ERR_NOT_FOUND`; unexpected server failure → `ERR_INVALID_INPUT` envelope — app.py:52-65
- §2.3 — revise — ambiguity — `limit` clamped to 1..100 and `offset` to ≥0, non-integers fall back to defaults — core.py:121-132
- §2.3 — insert — ambiguity — list ties on `created_at` broken by creation order — core.py:208-209
- §2.3 — insert — ambiguity — filter params are exact-match, `true`/`false` match booleans, unknown params ignored — core.py:223-235
- §2.5 — revise — mismatch — clock set is inert (no forfeiture sweep, no auto window-close); window enforced at submit, deadline at pay; clock may move forward or backward, unparseable → `ERR_INVALID_INPUT` — app.py:126-139 (sweep fns core.py:644-659 never called)
- §2.8 — insert — ambiguity — OCC tokens must be integers (digit strings coerced, other types → `ERR_INVALID_INPUT`); omitted or mismatched token → `ERR_STALE_VERSION` — app.py:658-662, 1381-1388
- §3.1 — insert — ambiguity — zone/booth creation gated to `PLANNING`/`APPLICATION_OPEN`/`JURY_REVIEW`/`SCHEDULING`, else `ERR_POSTURE_FORBIDS` — app.py:362, 405
- §3.1 — insert — ambiguity — Booth reads carry derived boolean `occupied` — app.py:425-428
- §3.1 — revise — mismatch — "two-letter home_region" → plain string, no format check — app.py:472
- §3.1 — revise — mismatch — suspension also blocks paying a pending assignment, not just submit/confirm — app.py:861-862
- §3.2 — insert — ambiguity — draft creation gated to `PLANNING`/`APPLICATION_OPEN`, profile must exist, and `vendor_profile_id` must equal `X-User-ID` — app.py:526-532
- §3.2 — insert — ambiguity — submit cap exhaustion → `ERR_CATEGORY_CAP_EXCEEDED`; open-applications before window start → `ERR_APPLICATION_WINDOW_CLOSED`; quorum < 2 → `ERR_INVALID_INPUT` — app.py:615-617, 217-221
- §3.2 — revise — mismatch — no automatic close at `application_window_end`; window closes only by coordinator action — app.py:227-231
- §3.3 — insert — ambiguity — scorecards accepted for applications in any status during `JURY_REVIEW` — app.py:738
- §3.3 — revise — mismatch — decide booth constraint: no booth matching category+tier → `ERR_BOOTH_CONSTRAINT_VIOLATION`; matching but all occupied → `ERR_BOOTH_DOUBLE_BOOKED` — app.py:671-687
- §3.3 — insert — ambiguity — selector's final tie after `created_at` settled by creation order — core.py:415
- §3.4 — revise — mismatch — begin-scheduling blocked only by `DRAFT`/`SUBMITTED` applications, not `IN_REVIEW` — app.py:242-245
- §3.4 — revise — mismatch — waitlist tie-break chain includes creation order between `created_at` and `vendor_profile_id` — app.py:255
- §3.4 — revise — mismatch — promotion scan runs per affected category only (no tier filter), promotes repeatedly, stops at first un-promotable head — core.py:577-605, 625-628
- §3.4 — insert — ambiguity — withdrawal clears `waitlist_rank` — app.py:637
- §3.5 — revise — mismatch — no automatic forfeiture when clock passes `payment_due_at`; expiry only blocks pay — core.py:644-651 (never called), app.py:863-866
- §3.5 — insert — ambiguity — forfeit endpoint allowed in any non-terminal posture; `CLOSED`/`CANCELLED` → `ERR_POSTURE_FORBIDS` — app.py:885-887
- §3.5 — insert — ambiguity — `REFUND` charges record `rounding_trace` = `refund` — core.py:614
- §3.5 — revise — mismatch — forfeiture cancels only settlements still `PENDING` or `COMPUTED` — core.py:621-624
- §3.5 — insert — ambiguity — confirm response carries the updated application — app.py:941
- §3.5 — insert — ambiguity — slot reservation gated to `SCHEDULING`/`LIVE`/`WEATHER_HOLD`, vendor ownership enforced, `starts_at` < `ends_at` else `ERR_INVALID_INPUT` — app.py:979-995
- §3.6 — insert — ambiguity — ticket sales accepted in every posture except `CLOSED`/`CANCELLED` — app.py:1058-1059
- §3.6 — insert — ambiguity — go-live failures: no ACTIVE assignment → `ERR_INVALID_STATE`; expired pending assignment → `ERR_PAYMENT_WINDOW_EXPIRED` — app.py:269-277
- §3.6 — revise — mismatch — redemption in non-`LIVE` posture → `ERR_POSTURE_FORBIDS` (not `ERR_TICKET_NOT_REDEEMABLE`, which now covers only not-`ISSUED` and `SEVERE` flag) — app.py:1129-1132
- §3.6 — insert — ambiguity — repeat exit scan → `ERR_INVALID_STATE`; `on_site` filter true/false semantics — app.py:1225-1226, 1185-1190
- §3.6 — revise — mismatch — pre-live cancel releases only `PENDING_PAYMENT`/`ACTIVE` assignments (not "all") and clears their booths' `assigned_application_id` — core.py:687-694
- §3.7 — insert — ambiguity — ledger posting gated to `LIVE`/`WEATHER_HOLD`, vendor ownership enforced — app.py:1241-1249
- §3.7 — revise — mismatch — `reversal_of_entry_id`, when present, must reference a same-assignment entry with negative `gross_cents` (negative rows without a reversal are accepted) — app.py:1251-1259
- §3.7 — insert — ambiguity — end-event before `closes_at` → `ERR_INVALID_STATE`; synthesized settlements zero-initialized with null `approved_by_user_id` — app.py:286-302
- §3.7 — revise — mismatch — dispute `reason` accepted but not persisted; wrong state → `ERR_INVALID_STATE`, non-owner → `ERR_FORBIDDEN` — app.py:1396-1410
- §3.7 — insert — ambiguity — settlement cancel from other states → `ERR_INVALID_STATE` — app.py:1434-1436
- §3.7 — revise — mismatch — close-event tolerates `CANCELLED` settlements ("APPROVED, PAID, or CANCELLED", not just "APPROVED or PAID") — app.py:313-316

Output file: `/home/ubuntu/github/CodingPRD/tasks/task_0997_craft_fair_maker_market_organizer/workspace/PRD_COMPLETED.md`.

---

## Pipeline complete

- workspace/PRD_COMPLETED.md exists (Step 9 output).
- worklog.md records Steps 1–9.
- Step 7 final stability sweep: 8/8 parallel rounds at 60/60 passed (results.1..8.json); no test/impl source files modified after that sweep (Steps 8–9 touched PRD docs only).
