# Worklog — task_1218_giving_circle_collective_philanthropy

## Step 1: Create task directory — 2026-08-12T00:05:00.000Z

Pre-assigned output folder `tasks/task_1218_giving_circle_collective_philanthropy` with `workspace/` subdirectory already exists (created by pipeline launcher). Step 1 auto-index scan skipped per instructions; directory verified present and empty. Scenario: Giving Circle & Collective Philanthropy Program (community giving circle). Difficulty parameter: "generate task hard than expert level!" (passed through to scaffold generator at Step 2 only).

## Step 2: Generate Scaffold — 2026-08-12T00:49:30.000Z

All three artifacts are generated, lint-clean, and verified. Summary:

## Files (all under `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/`)
- `SCAFFOLD.yaml` — 78,007 bytes (§1.0–§1.7 only; no difficulty/corner keys)
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — 91,930 bytes (single top-level key `scaffold_difficulty_design`)
- `SCAFFOLD_CORNER_DESIGN.yaml` — 185,494 bytes (single top-level key `scaffold_corner_design`)

## Counts
- **Entities: 14** (Circle, GivingCycle, Member, Membership, Contribution, Nonprofit, Nomination, SiteVisit, LearningSession, Ballot, GrantAward, Payout, GranteeReport, RolloverDecision) — flat topology, all FK reverse-reachable
- **Endpoints: 74** (incl. `POST /api/_clock/set_current_utc` with pinned default `2026-05-01T00:00:00Z`, computed `ledger`/`tally` reads)
- **State machines: 12** — guarded 9-phase cycle pipeline, cyclic loops (Nomination vetting/info, Membership renewal, GranteeReport resubmit, Payout retry, SiteVisit reschedule), parallel dimensions on GrantAward (payout_status × reporting_status), plus 2 OCC concurrency rules
- **Calculations: 9** (grant_budget dual-variant, pooled_balance, vetting_score dual-variant, award_allocation, payout_tranche_split, voting_tally, quorum_check, rollover_waterfall, host_admin_fee)
- **Validations: 20** (ordered priority table, categories auth → existence → state → safety → temporal → constraint → referential → fiscal)
- **Errors: 35**, all referenced by at least one validation/transition/design instance
- **Roles: 4** (CircleAdmin opaque, FinanceOfficer opaque, Member entity_backed:Member, GranteeContact entity_backed:Nonprofit; segregation-of-duties on payout approval)
- **§1.8 instances: 18 non-stub** (9 rules × 2, all differentiation clauses honored — e.g., dual variants on GivingCycle-fiscal vs Nomination-vetting domains; combinatorial modes (a) nested min/max share clamp vs (b) floor-then-remainder tranche rounding; cascades depth-3 clock-triggered vs depth-3 withdraw-triggered; boundary metrics quorum-count vs seat-count on distinct endpoints)
- **§1.9 instances: 54 total, 49 non-stub + 5 excluded_because stubs**, across all 9 claim-extraction-guide sections

## Verification
- `scaffold_lint.py`: **VERDICT: clean lint** (74 endpoints, 14 entities, 18 + 49 instances, 1,434 calls scanned; one initial FK-reachability miss on `GrantAward.nonprofit_id` fixed by adding the `nonprofit_id?` filter to `GET /api/awards`)
- Custom replay audit: zero unbound `${var}` placeholders; all 72 instance names unique across both design files; no forbidden concurrency vocabulary; all formula-derived asserts pre-computed as literals (e.g., provisional 190000 vs final 95000; vetting 69-fail vs 75-pass; award 123500; tranches 69825/29926; pro-rata 33250/33250)

## How "harder than expert level" was applied
Expert band is 10–15 entities / 20–32 endpoints / 18–30 errors; this scaffold sits at the top or beyond on every axis (14 / 74 / 35) *and* raises interaction density rather than padding CRUD: two dual-variant calculation pairs on different entity domains, two depth-3 transitive cascades from different triggers (clock sweep vs membership withdrawal), a frozen-snapshot quorum that resists post-entry withdrawal, phase-gated refund underfunding guarded against locked award obligations, segregation-of-duties keyed on `requested_by_user_id`, a three-level tally tie-break pinned to `created_at` (never `id`), two interval-conflict rules with deliberately different semantics (half-open adjacency for site visits vs 15-minute buffered gap for sessions), and OCC on both cycle advance and ballot recast.

## Step 3: Copy shared files — 2026-08-12T00:50:30.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1218_giving_circle_collective_philanthropy/workspace/INSTRUCTION.md` (1,424 bytes).

## Step 4: Generate PRD — 2026-08-12T01:05:00.000Z

PRD generated and verified on disk at `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/workspace/PRD.md`. The withheld `SCAFFOLD_DIFFICULTY_DESIGN.yaml` and `SCAFFOLD_CORNER_DESIGN.yaml` were never opened, nor was any sibling task directory.

**File stats**: 50,481 bytes, 343 lines, 7,068 words.

**Section list**: 1. Introduction (2 paragraphs); 2. Global Specifications with 10 subsections (2.1 RBAC with per-role identity prose, 2.2 response envelope emitted byte-verbatim from the canonical block, 2.3 Pagination, 2.4 Logical Clock, 2.5 Common Resource Properties, 2.6 Cycle Ledger & Derived-Field Reconciliation, 2.7 Monetary Precision, 2.8 OCC, 2.9 Validation Discipline & existence ordering, 2.10 Calendar Integrity); 3. Business Logic with 8 subsections organized along the annual-cycle timeline (founding → membership/retention → pooling/refunds → nomination/vetting → site visits/learning sessions → voting → award/payout pipeline → reporting/standing/closeout/rollover); 4. Endpoint Definitions (74-row, 4-column table); 5. Error Code Catalogue (35-row, 2-column table).

**Coverage audit (Zero-Silence Rule)**:
- **Contract 1 (Field-Name Coverage): PASS** — 98 required identifiers (all 14 entities' fields, all endpoint input/query/path params including the seven `*_id` path params, ledger/tally output keys, clock I/O) all present as backticked tokens; 0 missing.
- **Contract 2 (Rule Coverage): PASS** — validation priority ordering stated as an explicit mask-chain in §2.9 (auth → role → ownership → existence left-to-right → state → phase → membership-active → advance guards → business rules in scaffold order); both OCC rules expressed with write path, `expected_cycle_version`/`expected_ballot_version`, `ERR_STALE_VERSION`/412, no race framing; all 12 state machines' transitions, preconditions, and side effects rendered (including the two-hop OVERDUE → `SUSPENDED` → auto-`REJECTED` cascade, withdrawal pledge-voiding cascade, and retention cascade); all 9 calculations in reconstructible prose (dual-variant grant budget with `REFUND_REQUESTED`-counts-as-received rule, pooled balance, both vetting weight sets 40/30/30 vs 25/50/25, award allocation with 50000-cent floor and budget cap, floor-then-remainder tranche split, tally with strict-greatest first-choice and 3-level tiebreak, ceil quorum with equality-passes, pro-rata waterfall with floor-per-member and leftover-to-host, round-half-up host fee); all 35 error IDs named in §2/§3 near their triggers; all 43 state values and 53 enum values present verbatim; sibling branches (3-state reject/withdraw, DUE/OVERDUE/REJECTED submit, CANCELLED/NO_SHOW reschedule, dual rollover modes, dual budget/score variants) rendered with equal density.
- **Contract 3 (§3 Path Purity): PASS** — 487 backticked tokens scanned in §3; 0 path tokens, 0 bare HTTP methods, 0 method+path combos; endpoints referenced only via state-pair framing, role+verb, or capability description.
- Contract precision items: §2.2 verbatim confirmed byte-identical (including `req_RANDOMALPHANUM123456` and empty `"data": { }`); pagination defaults (10/1/100/0, `created_at` ascending, two documented deterministic overrides) stated; integer-cents precision with round-half-up/floor placement enumerated; all four role names exact with identity prose.

## Step 5: Generate Unit Tests — 2026-08-12T01:32:00.000Z

Generation complete and verified on disk. Summary:

## Files generated

**test_helpers/** (9 files) — `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/test_helpers/`
- `types.py` (6.8K) — 18 status/role enums, 14 entity TypedDicts (all carry id/created_at/updated_at/version per PRD §2.5)
- `api_client.py` (11.8K) — `ApiClient(GenericApiClient)` with 74 endpoint methods covering the full PRD §4 surface
- `api_errors.py` (3.6K) — all 35 error IDs with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` (5.0K) — per-entity assertions + ledger/tally shape checkers
- `factories.py` (4.3K) — payload factories with collision-free unique emails/EINs
- `constants.py` (1.2K) — PRD thresholds (70 vetting gate, 100-point budget, 70% upfront tranche, 50000-cent award floor, 15-minute buffer, 7-day window, 90/365-day report deadlines, canonical clock waypoints)
- `test_users.py` (1.9K) — shared opaque-role headers (`admin-1`, `fin-1`) + mandatory per-instance builders for entity-backed Member/GranteeContact + `EMPTY_HEADERS`
- `fixtures.py` (17.8K) — layered composites: `setup_pooling` → `setup_nomination_phase` → `setup_nomination_in_vetting` → `setup_voting` → `setup_award` → `setup_reporting`, plus OCC-safe `advance_cycle`/`try_advance_cycle`, `vet_to_finalist`, `setup_second_cycle_nomination`, session/RSVP helpers; all ownership-gated calls thread real entity ids
- `__init__.py` (3.4K) — barrel export

**test_suite/** (9 files) — `conftest.py` + 8 test files, **85 tests total** (pytest collection verified)

## Queue A (difficulty, §1.8): 36 tests — every rule × instance has exactly 2
dual_variant_calc (4: budget divergence ×2, vetting profile flip ×2), combinatorial_formula (4: award min/max ×2, tranche floor/remainder ×2), non_linear_state_machine (4: info-loop ×2, award parallel dims ×2), transitive_cascade (4: overdue→suspend→reject ×2, withdraw-void-budget ×2), priority_pair_validation_conflict (4: phase-beats-tier ×2, window-beats-finalist ×2), boundary_precision_check (4: quorum exact-equality ×2, session capacity ×2), cross_entity_state_dependency (4: ballot-active-membership ×2, receive-requires-POOLING ×2), resource_temporal_overlap (4: half-open adjacency ×2, 15-min buffer ×2), compensating_invariant (4: receive/refund conservation ×2, cast/recast points conservation ×2).

## Queue B (corner, §1.9): 49 tests — every non-stub instance has ≥1
entities 7, state_machines 9, calculations 4, validations 4, endpoints 3, errors 15, rbac 4, complexity_layers 2, consistency_model 1.

## Instances skipped
Only the 5 declared `excluded_because:` stubs (computed_pooled_balance_after_receive + 4 complexity-layer coverage markers); all 5 cross-references verified to resolve to real §1.8 instances. No non-stub instance was skipped — every instance passed the PRD-first two-condition filter (PRD.md states each rule verbatim with uniquely-derivable outcomes).

## Stage-2 self-audit results
- Tag coverage: all 85 tests carry exactly one `Design:` tag as the docstring's final line; all tags resolve to real instances; no stub is tagged; no untagged/dual-tagged tests. Queue A ≥2 everywhere, queue B non-stub ≥1 everywhere.
- PRD citation check: automated verbatim sweep — every quoted sentence in all 85 docstrings survives literal substring match of PRD.md (0 mismatches after fixing 5 elided/truncated citations to full-sentence form).
- No `pytest.mark.skip`/`skipif`/`xfail`, no "scaffold" references anywhere in generated code.
- Notable adjudications: absolute `version == 2` assertions were replaced with PRD-pinned relative `version == captured + 1` (PRD never fixes the initial version); `nonprofit_defaults_standing_good` asserts `standing == GOOD` only (initial version value not PRD-derivable); voting-window timestamps compared as parsed instants (PRD pins the instant, not the string format).

## Step 6: Generate Implementation — 2026-08-12T01:32:00.000Z

Done. Implementation complete and verified.

## Summary

**Files written** (all under `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/workspace/implementation/`):

| File | Size | Purpose |
|------|-----:|---------|
| `start.sh` | 396 B | Foreground launcher, `exec python3 app.py`, guarded `pip install`, reads `$PORT` (default 10000), binds `0.0.0.0` |
| `requirements.txt` | 16 B | `flask>=3.0,<4.0` |
| `app.py` | 68,751 B | Flask entry point, error handlers, all 74 route handlers |
| `db.py` | 704 B | In-memory `Store` (dicts keyed by id); logical clock starts at `2026-05-01T00:00:00Z` |
| `errors.py` | 2,552 B | All 35 error-id constants + `ApiError` |
| `middleware.py` | 726 B | `X-User-ID` / `X-User-Role` extraction, role gating |
| `response.py` | 2,721 B | Envelope (`meta` / `response_type` / `data`), pagination (`limit`/`offset`/`total_count`/`has_more`, defaults 10/1/100/0), ISO-8601 3-fractional-digit timestamps, `req_…` ids |
| `services.py` | 11,836 B | Ledger/budget recompute, vetting score (BALANCED vs EQUITY_FIRST, half-up via `Decimal`), tally + winner tie-break, clock-driven transitions (report OVERDUE cascade → nonprofit SUSPENDED → in-flight nomination REJECTED; visit NO_SHOW), rollover waterfall |

**Route count:** SCAFFOLD endpoint table declares 74 (method, path) pairs; Flask registers exactly 74 — 0 missing, 0 extra. (Verified programmatically by diffing `app.url_map` against `SCAFFOLD.yaml` after path-param normalization.)

**Syntax:** `python3 -m py_compile` passes on all six `.py` files.

**Boot smoke test:** `PORT=18743 bash start.sh` booted, served, and was killed cleanly. Verified:
- 401 `ERR_UNAUTHENTICATED` with no headers
- 200 empty-array list with `meta.{limit,offset,total_count,has_more}`
- 200 clock set → `{"current_utc": "2026-05-02T00:00:00.000Z"}`
- 201 circle create with system fields (`id`, `created_at`, `updated_at`, `version`)

**End-to-end sanity flow** (on a second boot): create circle → cycle (DRAFT) → member → membership (INVITED) → member accept → advance ×2 with correct OCC versions (200) → stale advance (412 `ERR_STALE_VERSION`) → below-minimum pledge (409 `ERR_BELOW_TIER_MINIMUM`) → valid pledge (201, PLEDGED) → admin receive (200) → ledger shows `received=20000, pooled=20000, provisional=final=18000` (20000 − 10% fee half-up − 0 reserve), confirming the budget calculation and immediate derived-field reconciliation.

**Key contract compliance:**
- In-memory only; zero seeding at startup — store dicts start empty, clock is the only initialized state.
- `start.sh` guards `pip install` behind `python3 -c "import flask"` so per-test reboots don't contend on pip.
- OCC via `expected_cycle_version` (cycle advance, checked first before phase guards) and `expected_ballot_version` (ballot recast), both → 412 `ERR_STALE_VERSION`.
- Validation priority: auth → role → ownership → existence (left-to-right) → from-state → phase → membership-active → business rules (SoD → temporal windows → uniqueness → overlap/buffer → capacity → referenced-entity state → ballot refs/points → fiscal thresholds).
- Money as integer cents; `Decimal` + `ROUND_HALF_UP` only where the PRD names it (fee, vetting score, award raw); floor for tranche 1 and pro-rata member credits.
- List ordering: `created_at` ASC default; payouts by `tranche` ASC; reports by `due_at` ASC.

## Step 7: Run tests and iterate — 2026-08-12T01:41:00.000Z

Clean sweep: all 8 rounds pass 85/85.

Summary:
- Iterations run: 2 (first sweep: 62/85 with 23 deterministic failures in every round; second sweep: clean).
- Tests deleted: none.
- Fixes applied to `test_helpers/`:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/test_helpers/fixtures.py` — `setup_award()` and `setup_reporting()` gained a positional `name: str = "Circle"` parameter forwarded to `setup_voting(name, ...)`; 21 tests call them with a positional circle name (matching the `setup_voting`/`setup_pooling` signature convention), and the keyword-only signatures raised `TypeError: setup_award() takes 0 positional arguments but 1 was given`.
- Fixes applied to `test_suite/`: none.
- Fixes applied to `implementation/`:
  - `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/workspace/implementation/services.py` — `recompute_cycle_ledger()`: the pooled-balance formula double-subtracted refunds (a REFUNDED contribution is already excluded from `received_total_cents` per PRD §2.6's definition, and was then subtracted again as the refunded total), yielding `pooled_balance_cents == -100000` after a full receive+refund instead of 0. Per PRD §2.6 the formula's "received funds" is the gross inflow (received + refunded), so the refunded terms cancel; the refund subtraction was removed from the pooled computation.
- Final sweep evidence: results.1.json 85/85, results.2.json 85/85, results.3.json 85/85, results.4.json 85/85, results.5.json 85/85, results.6.json 85/85, results.7.json 85/85, results.8.json 85/85.

## Step 8: Finalize PRD — 2026-08-12T01:43:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/workspace/PRD_FINALIZED.md` written with exactly one inline clarification.

**Line counts / delta**
- PRD.md: 342 lines; PRD_FINALIZED.md: 342 lines (0% line-count delta; one sentence inserted inline into §2.6, line 101 — single-line diff confirmed).

**Changes**
- §2.6 (The Cycle Ledger and Derived-Field Reconciliation) — insert — added a clarifying sentence: "received funds" in the pooled-balance formula means the gross inflow (including funds later refunded), so the refunded terms cancel and pooled balance equals `received_total_cents` − released total − transferred admin fee + rollover in − rollover out; the refund is never subtracted twice — `implementation/services.py:108-139` (`recompute_cycle_ledger`).

**Pre-edit search log (edit 1)**
- (a) Subject: the definition of the `pooled_balance_cents` formula in PRD §2.6 — specifically whether "received funds" means the previously defined `received_total_cents` (RECEIVED + REFUND_REQUESTED only) or the gross inflow, given the sentence then says to subtract the refunded total.
- (b) Impl paths enumerated and read/grepped: `services.py:108-152` (the sole formula site: `pooled = received - released - admin_fee_transferred + rollover_in - rollover_out`, no refund subtraction); `app.py:203` (cycle init `pooled_balance_cents: 0`); `app.py:308` (closeout gate `pooled_balance_cents != 0`); `app.py:399/429` (ledger read returns the ten figures); `app.py:539/638/682/727/1307/1458` (recompute callsites after financial mutations); `app.py:708-728` (refund-approval flow and the `pooled - amount < obligations` underfunding guard at `app.py:722`); `app.py:1656/1663/1691` (rollover execution capturing pooled as residual); PRD cross-references at lines 155, 159, 215, 219. All consume the stored value; only `services.py:135-139` defines it.
- (c) Wording adjustment: the inserted sentence both explains the cancellation reading AND restates the formula explicitly in terms of the defined figure names (`received_total_cents`, released, fee, rollover pair), so a fresh implementer cannot pick the double-subtracting reading regardless of which clause they anchor on. Verified consistent with the refund-approval narrative at PRD line 159 (pooled drops by the refunded amount because the contribution leaves `received_total`, not because of a separate subtraction).

**Non-edits, with evidence**
- test_helpers `fixtures.py` signature fix (`setup_award`/`setup_reporting` positional `name` parameter) — pure test-harness plumbing; no PRD-visible behavior. No edit made.
- The `services.py` refund double-subtraction fix was a bug being brought into alignment with the gross-inflow reading of §2.6, but §2.6's prose did not uniquely determine that reading (the literal "received_total minus refunded_total" reading is grammatically defensible and is exactly what the buggy code did). Hence one clarifying sentence rather than zero edits.

## Step 9: PRD completeness scan — 2026-08-12T01:58:00.000Z

Done. `PRD_COMPLETED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_1218_giving_circle_collective_philanthropy/workspace/PRD_COMPLETED.md`.

## Summary

**Source vs output:** `PRD_FINALIZED.md` (342 lines / 50,814 chars) → `PRD_COMPLETED.md` (342 lines / 55,577 chars). Char delta: **+4,763**. All changes are in-paragraph inserts/revisions; no new sections or paragraphs; line count unchanged (342 → 342).

**Counts:** 17 ambiguity-pins, 2 mismatch-revisions (19 edited passages total).

### Changes

- §2.1 — insert — ambiguity — pinned that ownership checks apply only to writes; all GET endpoints are open to every authenticated role with no ownership scoping — implementation/app.py (all GET handlers use `require_roles(*ALL_ROLES)`, e.g. app.py:158-162).
- §2.2 — revise — ambiguity — pinned `api_request_timestamp` as wall-clock, the sole non-logical-clock timestamp — implementation/response.py:20-22,38-45.
- §2.3 — insert — ambiguity — pinned pagination clamping: unparseable/out-of-range `limit`/`offset` fall back to defaults/bounds, never rejected — implementation/response.py:85-109.
- §2.3 — insert — ambiguity — pinned tiebreaks: payouts sort by `(tranche, created_at)`, reports by `(due_at, created_at)`; and all list filters are exact-match, case-sensitive equality — implementation/app.py:1416, 1506, and list-filter handlers (e.g. app.py:478).
- §2.4 — insert — ambiguity — pinned clock endpoint accepts any valid ISO 8601 timestamp unconditionally (no monotonicity); missing/unparseable `to_iso8601` → `ERR_INVALID_REQUEST` — implementation/app.py:108-119.
- §2.5 — insert — ambiguity — pinned `version` starts at 1 and `created_at`/`updated_at` are stamped from the logical clock — implementation/services.py:41-53.
- §2.8 — insert — ambiguity — missing or non-integer `expected_cycle_version`/`expected_ballot_version` → `ERR_INVALID_REQUEST` (400) — implementation/app.py:247-251, 1345-1349.
- §2.9 — revise — mismatch — carved out guard-order deviations: start-vetting and advance-to-finalist check cycle-phase before from-state; ballot recast checks voting window before membership-active — implementation/app.py:892-895, 935-938, 1356-1358.
- §3.1 — insert — ambiguity — new cycle's initial ledger: six totals and pooled balance at zero; both budget variants initialize to `0 − fee(0) − operating_reserve_cents`; `budget_locked` starts false — implementation/app.py:196-207.
- §3.1 — insert — ambiguity — advancing a `CLOSED` cycle fails `ERR_INVALID_STATE`, evaluated after the OCC precondition — implementation/app.py:257-258.
- §3.3 — insert — ambiguity — non-positive/non-integer `amount_cents` is malformed (`ERR_INVALID_REQUEST`), distinct from `ERR_BELOW_TIER_MINIMUM` — implementation/app.py:617-619.
- §3.4 — insert — ambiguity — once-per-cycle nomination rule counts nominations in any status, including `WITHDRAWN`/`REJECTED` — implementation/app.py:817-820.
- §3.4 — revise — ambiguity — scoring PATCH has no state/phase gate; absent/null inputs left unchanged; no-op PATCH returns the nomination without a version bump — implementation/app.py:866-882.
- §3.4 — revise — mismatch — finalist promotion: phase gate runs before from-state; a still-null `vetting_score` also fails with `ERR_VETTING_SCORE_BELOW_THRESHOLD` — implementation/app.py:935-947.
- §3.5 — revise — ambiguity — site-visit scheduling gates only on nomination existence (no nomination-status or cycle-phase check); `findings_note` optional on completion; reschedule excludes the visit itself from its overlap set — implementation/app.py:1004-1028, 1063-1066, 1101.
- §3.5 — insert — ambiguity — RSVP does not gate on the session's own status — implementation/app.py:1192-1210.
- §3.6 — revise — ambiguity — voting-window failure also fires `ERR_VOTING_WINDOW_CLOSED` when the cycle is not in `VOTING`; structurally malformed allocation entries yield `ERR_INVALID_REQUEST`; points-budget shape validated before nomination references; nonexistent nomination id → `ERR_NOT_FOUND`, wrong-cycle/non-finalist → `ERR_NOT_FINALIST`; recast guard order pinned (window before membership-active) — implementation/app.py:1237-1279, 1356-1361.
- §3.6 — insert — ambiguity — tally view: `finalist_points` entry shape (`nomination_id`, `total_points`, `first_choice_count`) and ordering (points desc, first-choice desc, `created_at` asc); `quorum_required` reads 0 before the snapshot exists — implementation/services.py:242-263.
- §3.8 — revise — ambiguity — pro-rata weight is the membership's contributions counted as received (`RECEIVED` or `REFUND_REQUESTED` per §2.6); zero combined weight or non-positive residual credits no one, host retains all — implementation/app.py:1666-1688.
