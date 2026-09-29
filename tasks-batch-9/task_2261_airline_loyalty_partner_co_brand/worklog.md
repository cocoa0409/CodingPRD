# Worklog — task_2261_airline_loyalty_partner_co_brand

## Step 1: Create task directory — 2026-09-01T11:50:17.773Z

Created `tasks/task_2261_airline_loyalty_partner_co_brand/` and `tasks/task_2261_airline_loyalty_partner_co_brand/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Generate scaffold — 2026-09-01T13:23:32.795Z

All three artifacts are complete and lint clean.

## Generated files
- `/home/ubuntu/github/CodingPRD/tasks/task_2261_airline_loyalty_partner_co_brand/SCAFFOLD.yaml` (§1.0–§1.7)
- `/home/ubuntu/github/CodingPRD/tasks/task_2261_airline_loyalty_partner_co_brand/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8)
- `/home/ubuntu/github/CodingPRD/tasks/task_2261_airline_loyalty_partner_co_brand/SCAFFOLD_CORNER_DESIGN.yaml` (§1.9)

## Scaffold profile
`difficulty_level: beyond_expert`; archetypes `ledger_reconciliation` / `multi_party_negotiation`; `entity_topology: flat`, `state_machine_shape: cyclic`, `role_model: segregation_of_duties`, `consistency_model: immediate`; complexity layers = dual_variant_calculation, cascading_side_effects, optimistic_concurrency, rate_threshold_triggers.

- **13 entities**: LoyaltyProgram, CoBrandIssuer, MileSaleAgreement, MilePurchaseOrder, MemberAccount, MileTransaction, PromotionCampaign, AwardInventoryWindow, AwardBooking, PartnerAirlineAgreement, PartnerSettlementRun, DeferredRevenuePosting, ProgramChangeNotice, FraudCase (self-referential MileTransaction reversal link; DeferredRevenuePosting immutable, no version).
- **9 state machines**, including parallel fulfillment/settlement dimensions on MilePurchaseOrder, a cyclic recognition cycle on LoyaltyProgram (OPEN→CLOSING→LOCKED→OPEN advancing current_period), and a negotiation loop on MileSaleAgreement (DRAFT→ISSUER_REVIEW→COUNTERED→revise→…→RATIFIED→ACTIVE→SUPERSEDED).
- **8 calculations**: mile_purchase_order_pricing (tiered_pricing + provisional/final variants), breakage_and_deferred_revenue (aggregation + historical/forward variants), earning_credit_with_multipliers (weighted_scoring), award_dynamic_pricing (threshold ladder), elite_qualification_and_rollover (waterfall_allocation), partner_settlement_run (chronological), fraud_risk_and_clawback (weighted_scoring), member_reaction_index (weighted_scoring).
- **36 validation priorities** (1 UNAUTHENTICATED → 36 PERIOD_ALREADY_POSTED), with deliberate priority pairs: MEMBER_FROZEN(12) over INSUFFICIENT_MILES(31), WINDOW_IN_PAST(15) over PROMOTION_WINDOW_OVERLAP(19), RECIPROCITY_SUSPENDED(24) over AWARD_WINDOW_CLOSED(25)/AWARD_SEATS_UNAVAILABLE(28).
- **66 endpoints**, **46 error codes** (every code triggerable — audited, zero uncovered), **7 roles** (ProgramAdmin, PartnerManager, ContractsOfficer, RevenueAccountant, FraudAnalyst, IssuerRepresentative `entity_backed:CoBrandIssuer`, Member `entity_backed:MemberAccount`), **3 concurrency_rules** (agreement/window/program `expected_*_version` → ERR_STALE_VERSION 412).

## Design instance counts
- **§1.8: 18 instances** — all 9 difficulty rules × 2.
- **§1.9: 79 instances** across all 9 sections — entities 12, state_machines 15, calculations 13, validations 9, endpoints 5, errors 13, rbac 7, cross_cutting_complexity_layers 4, consistency_model 1. 65 carry full `test_recipe`s; 14 are `excluded_because` stubs citing a §1.8 instance (all citations resolve by name).

## Verification
`scaffold_lint.py` → `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` (544 calls scanned across 66 endpoints). Also verified independently: all 97 instance names unique across both design files, no stub carries a `test_recipe`, every non-stub has grounds/claim_type/distinguishing_aspect/test_recipe, and SCAFFOLD.yaml carries neither design key. One SCAFFOLD.yaml fix was applied during the pass: `ISSUER_UTILIZATION_ALERT_BPS` was referenced by the ratification cascade but unvalued, now pinned to 9000 on the CoBrandIssuer `status` description. No sibling task directory was read at any point.

## Step 3: Copy shared files — 2026-09-01T13:23:32.795Z

Copied `INSTRUCTION.md` → `tasks/task_2261_airline_loyalty_partner_co_brand/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-09-01T13:39:04.648Z

All three hard contracts pass. Final state verified.

**PRD written:** `/home/ubuntu/github/CodingPRD/tasks/task_2261_airline_loyalty_partner_co_brand/workspace/PRD.md` (460 lines).

**Structure**
- `# Airline Loyalty Partner & Co-Brand Program Economics API — Product Requirements Document`
- §1 Introduction — 3 paragraphs (four coupled ledgers; drift pain points; logical clock + integer-only arithmetic).
- §2 Global Specifications — 11 subsections: 2.1 RBAC (all 7 roles, `X-User-ID`/`X-User-Role`, opaque vs entity-backed identity for `IssuerRepresentative`→`CoBrandIssuer` and `Member`→`MemberAccount`), 2.2 API Response Structure (byte-identical to `section-2.2-response-structure.md`, verified programmatically), 2.3 Pagination + per-collection filter names, 2.4 common properties incl. the two `common_fields: false` append-only ledgers (`MileTransaction`, `DeferredRevenuePosting` carry only `id`/`created_at`), 2.5 cents/centicents/basis points and rounding-position rules, 2.6 logical clock (startup `2026-08-01T00:00:00Z`, never wall clock), 2.7 period lock, 2.8 stale-version protection, 2.9 the full 36-rung validation ladder, 2.10 cascade propagation, 2.11 path/FK resolution and programme boundaries.
- §3 Business Logic — 9 subsections (programme foundation + epoch runner; agreement negotiation/ratification; purchase-order draw/invoice/reverse; member accounts, mile ledger and campaigns; award inventory, dynamic pricing and booking lifecycle + settlement; elite qualification/rollover/status match; fraud detection and clawback; change notices and reaction risk; period close and breakage).
- §4 Endpoint Definitions — 4-column table, all 66 endpoints (paths verified equal to the scaffold set).
- §5 Error Code Catalogue — 2-column table, all 46 error IDs.

**Hard Contract reports**

```
Field coverage check:
- entities[].fields: 147 required (162 declarations / 13 entities), 147 present, 0 missing
- endpoints[].request_body (+ path params): 87 required, 87 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose (ordered ladder §2.9), 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write endpoint + expected_<parent>_version + ERR_STALE_VERSION/412 all named), 0 missing — plus the fourth version-carrying create (programme change notice / expected_program_version) named per validation priority 9
- state_machines[].transitions: 47 checked, 47 fully expressed, 0 missing
- calculations[]: 8 checked, 8 fully expressed (both pricing variants, both breakage variants, all 4 stacking modes, all 7 award-pricing steps, waterfall, settlement, fraud scoring, reaction index), 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 36 non-trivial side-effect sets checked (66 endpoints scanned), 36 expressed, 0 missing
- entities[].fields[] structured content: 147 checked, 147 reconstructible from prose (enums, defaults, bounds, uniqueness, tier_schedule shape, counter definitions), 0 missing
- sibling-branch symmetry: 16 groups checked, 16 with equal prose density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 1057
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional checks: no fuzzy-language or pseudocode residue (grep for `>=`, `==`, `min(`, `floor(`, `round_half_up(`, "approximately", "roughly", "conservatively", "appropriate" returns zero hits); §4 exactly 4 columns / 66 rows, §5 exactly 2 columns / 46 rows; deliberate ladder exclusions stated (out-of-range `seats` must surface as `ERR_SEAT_COUNT_INVALID`, inverted intervals as `ERR_INVALID_INTERVAL`, never `ERR_INVALID_REQUEST`). The two withheld design YAMLs were never opened, grepped, or referenced.

## Step 5: Generate unit tests — 2026-09-01T14:13:17.651Z

Complete.

## Files written

**`test_helpers/`** (9 files, 274 public names, imports cleanly): `types.py`, `api_client.py` (66 endpoint methods), `api_errors.py` (46 codes + HTTP status map), `constants.py`, `test_users.py`, `factories.py`, `assertions.py`, `fixtures.py`, `__init__.py` (single barrel import surface).

**`test_suite/`**: `conftest.py` + 13 domain-named test files. **119 test functions / 130 collected cases**, no file untagged.

| Queue | Tests | Instances covered |
|---|---|---|
| A (Difficulty, §1.8) | 49 | **18/18** (≥2 each) |
| B (Corner, §1.9) | 70 | **65/65** non-stub (≥1 each) |

Files 01–05 carry queue A; 06–13 carry queue B, split by section (entities, state_machines, calculations, validations, endpoints, errors, rbac, cross_cutting + consistency_model).

## Verification (all passing)

A checker at `/tmp/verify_2261.py` confirms: exactly one `Design:` line per test as the docstring's last line; every tag resolves to a real **non-stub** instance with a matching rule_id/section; every `PRD §X.Y: "..."` quotation survives a literal substring grep of PRD.md; coverage thresholds met; no `mark.skip/skipif/xfail`, no mocking, no occurrence of "scaffold"; no `api.*` call to a non-existent client method. Plus `pytest --collect-only` clean and pyflakes reporting zero undefined names or unused imports in `test_suite/`.

The 14 `excluded_because:` corner stubs were skipped silently — their assertions are owned by queue A.

## Instances skipped: none

Every one of the 83 non-stub instances is translated. Sub-assertions dropped where the PRD does not uniquely derive them (gaps left as gaps, never weakened):

- **Absolute `version` literals** on create/after-N-transitions — §2.4 fixes only "increments by exactly one", never an absolute value. Replaced with increment-against-captured-prior, or `assert_<entity>()` sanity.
- **Exact timestamp string equality** (`hold_expires_at`, `announced_at`, `last_settlement_run_at`, `status_match_expires_at`, `epoch_at`) — the PRD pins the *instant* but mandates three fractional digits only for `created_at`/`updated_at`, so `...00:00:00Z` and `...00:00:00.000Z` are both faithful. Relaxed to instant-prefix + ISO-8601 checks.
- **`negotiated_by_user_id == null` at draft** — the PRD describes that field only as stamped *at submission*; its pre-submission value is unstated.
- **`FraudCase.freeze_applied == true` at score 17** — §3.7 sets that flag only at score ≥70; no substantiation hop mentions back-filling it.
- **`detection_score == 40` follow-on redemption succeeding** — §2.9 rung 12 requires `security_state == NORMAL` to post a ledger row, and a WATCH member is not NORMAL, so the index's expected 201 is not PRD-derivable.
- Two non-request-expressible claims (no PATCH declared for postings; undeclared query-param behaviour).

## Two design-index/helper defects adjudicated in the PRD's favour

1. **`negotiation_round`**: two corner instances assert `0`; PRD §3.2 says a draft "starts in `DRAFT` with `negotiation_round` at 1". Tests assert **1**.
2. **`ERR_VOLUME_COMMITMENT_EXCEEDED` status**: index says 422; PRD §2.9 rung 32 and the §5 catalogue both say **409**. Tests assert 409.

I also **fixed a bug in `test_helpers/constants.py`** that two agents independently flagged: `CHANGE_TYPE_SEVERITY` had `AWARD_PRICING: 40, EARN_STRUCTURE: 50`, inverting PRD §3.8 ("40 points for `EARN_STRUCTURE`, 50 for `AWARD_PRICING`"). Now corrected; I re-audited the neighbouring §3.8 constants (lead-time factors, grandfather relief, exposure) and they match the PRD. No test imported the constant, so no test outcome changed.

Nothing under `workspace/implementation/` was read, listed, or created.

## Step 6: Generate implementation — 2026-09-01T14:13:17.651Z

Implementation complete and smoke-tested.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2261_airline_loyalty_partner_co_brand/workspace/implementation/`)

| File | Role |
|---|---|
| `start.sh` | Foreground launcher, `exec python3 app.py`, guarded pip install (no-op once Flask present, so per-test reboots are fast) |
| `requirements.txt` | `Flask==3.0.3` |
| `app.py` | App factory, 6 blueprints, `ApiError`/404/405/catch-all handlers that keep the envelope, `0.0.0.0:$PORT` (default 10000), `threaded=True`, no reloader |
| `db.py` | `Store` = 13 empty dicts + logical clock pinned to `2026-08-01T00:00:00Z` + `_seq` counter. Nothing seeded |
| `response.py` | Envelope (`meta.api_request_id` `req_<20 alnum>`, `api_request_timestamp` 3-digit ms), `object`/`array`/`error` discriminator, pagination inside `meta` |
| `middleware.py` | `X-User-ID`/`X-User-Role` auth (7 roles), RBAC, body parsing, `limit`/`offset` (10 / 1–100 / 0) |
| `validators.py`, `errors.py` | Rung-7 schema helpers; all 46 error IDs with their HTTP statuses |
| `calc.py` | 8 calculations, all `Decimal` + `ROUND_HALF_UP` via a single `rhu()` helper, plus every constant table |
| `services/core.py` | Row minting, `dump`, per-request-idempotent `touch`, FK/scope helpers, window recompute, seat release, issuer aggregate, ledger insert, cascades |
| `routes/{programs,issuers,members,awards,governance,ops}.py` | All 66 endpoints |

## Endpoints
7 programme/posting, 18 issuer (issuers + agreement 8-step lifecycle + order 7-step lifecycle), 10 member (accounts, status-match grant/resolve, cycle close/restate, ledger), 18 award (campaigns, windows + capacity-control PATCH, bookings incl. ticket/cancel/refund, partner airlines + settlement-runs), 11 governance (notices announce/rollback, fraud cases investigate/substantiate/dismiss), 2 test utilities (`/_clock/set_current_utc`, `/_ops/run-epoch`) = **66**.

## Design decisions
- **PRD prose wins over scaffold structure** where they diverge (e.g. substantiation's security-state outcome; ladder priority overriding narrative order — volume ceiling before issuer-suspended on order create; frozen/locked before hold-expired/insufficient-miles on ticketing).
- **36-rung ladder is encoded literally** in each handler, in ascending rung order, with a comment naming the rung.
- `version` starts at 1; `touch()` bumps at most once per request per row; cascaded children get their own bump. `MileTransaction` and `DeferredRevenuePosting` expose only `id` + `created_at` (verified in the running server).
- **Two clocks**: wall clock for `created_at`/`updated_at` plus a hidden `_seq` for stable `created_at ASC` ordering; the logical clock drives every temporal decision and the fields tied to it (`hold_expires_at`, `status_match_expires_at`, `announced_at`, `last_settlement_run_at`, `epoch_at`).
- Epoch recompute bumps a window's `version` only when a derived field actually changed; seat movement always touches.
- Member/issuer scope: 403 on detail reads and on explicit `member_id` filters, silent filtering for role-scoped lists.

## Verification
Three sequential `start.sh` boots each reported `total_count: 0` (store empty, zero carry-over). End-to-end exercises passed: full agreement negotiation cycle DRAFT→ISSUER_REVIEW→COUNTERED→DRAFT→ISSUER_REVIEW→RATIFIED→ACTIVE with SoD rejection; order create/issue/invoice/settle with true-up into deferred revenue; earn with `MULTIPLICATIVE` stacking; booking price/hold/ticket/refund; per-booking `OUTBOUND_ONLY` settlement rounding (33750 → 16875 + 16875); notice announce with reaction index; fraud freeze → substantiate → 5-hop clawback; posting + `ERR_PERIOD_ALREADY_POSTED` + period cycle OPEN→CLOSING→LOCKED→OPEN advancing `current_period`. Error paths return the right codes (401/403/404/400/409/412/402). Error-ID→HTTP-status table cross-checked programmatically against SCAFFOLD.yaml: no missing IDs, no status mismatches. No `open()`, sqlite, `/tmp`, or serialisation anywhere in the source; `__pycache__` removed.

## Step 7: Run tests and iterate — 2026-09-01T14:28:35.846Z

Clean 8/8 sweep achieved. All artifacts tidied (results files and `__pycache__` removed, no on-disk persistence in the implementation).

## Summary

**Iterations run:** 3 sweeps (8 parallel rounds each).
- Sweep 1: 114/130 in all 8 rounds — 16 failing tests, fully deterministic (each failed in 8/8 rounds; no flakiness anywhere in the suite).
- Sweep 2: 128/130 in all 8 rounds — 2 failing tests.
- Sweep 3: **130/130 in all 8 rounds.**

**Tests deleted:** none. Every failure traced to a test-layer defect (STEP 2), not to PRD silence — the implementation was never modified.

**Fixes applied to `test_helpers/`:** none needed. The bugs lived in `test_suite/` directly.

**Fixes applied to `test_suite/`:**

1. **Envelope double-unwrap (16 tests, 3 files).** `prd_bench_local_runner.testing.validate_success()` already returns `body["data"]`, but 15 call sites re-indexed the result with `["data"]`, raising `KeyError: 'data'` on every 2xx path they guarded. Fixed in `test_suite/test_04_award_windows_holds_and_compensation.py` (9 sites), `test_suite/test_07_lifecycle_state_machines.py` (7), `test_suite/test_13_cross_cutting_consistency_layers.py` (4). This was the wide-reach root cause behind 14 of the 16 failures — the tests were asserting nothing about the implementation, they were crashing in their own plumbing.

2. **ISO-8601 fractional-digit rendering (2 tests, `test_suite/test_04_award_windows_holds_and_compensation.py`).** `test_hold_expires_seventy_two_hours_after_it_was_created` asserted `hold_expires_at == "2026-08-04T00:00:00Z"` and `test_campaign_starting_exactly_at_incumbent_window_end_is_adjacency` asserted `window_start == "2026-10-01T00:00:00Z"`, while the server rendered `...00:00:00.000Z`. Per STEP 1c (partial coverage): PRD §3.5 verbatim pins the *instant* ("`hold_expires_at` is stamped as the logical clock's now plus 72 hours") but §2.4 mandates three fractional digits only for `created_at`/`updated_at`, so the rendering of `hold_expires_at`/`window_start` is not uniquely derivable — both `Z` and `.000Z` are faithful. Kept the covered assertion (the instant) and dropped the uncovered one (the exact string) by switching to `.startswith("2026-08-04T00:00:00")` / `.startswith("2026-10-01T00:00:00")`, which is the convention the rest of this suite already uses for clock-derived instants (`announced_at`, `epoch_at`, `status_match_expires_at`, and the other `hold_expires_at` assertion in `test_11`).

**Fixes applied to `implementation/`:** none. No PRD-required check was weakened or removed, and no endpoint, field, or side effect was added.

*Orchestrator note:* a confirmation 8-round sweep was re-run after Step 7 exited (the subagent had deleted its results files during cleanup). All 8 rounds: `passed=130 / total=130 / failed=0`. `workspace/implementation/results.{1..8}.json` persisted.

## Step 8: Finalize PRD — 2026-09-01T14:31:58.743Z

Done. One edit, tracing to `<step_7_diff>` item 2.

## Line counts
- `PRD.md`: 460 lines
- `PRD_FINALIZED.md`: 462 lines
- Delta: +2 lines (+0.43%)

## Changes
- **§2.4 Common Resource Properties and Immutable Ledger Rows** — *insert* — a new paragraph pinning ISO-8601 rendering as system-wide for **all** instant-valued fields (not just `created_at`/`updated_at`): exactly three fractional digits plus trailing `Z`, including when the fractional part is zero (`2026-08-04T00:00:00.000Z`, never `...00:00:00Z`); client-supplied instants normalised to UTC and echoed in the same form; unset instants render `null`; calendar-date and `YYYY-MM` period fields explicitly excluded — `implementation/response.py:12-21` (`iso_ms`), `implementation/services/core.py:83-93` (`dump` converts every `datetime` via `iso_ms`), `implementation/routes/ops.py:25,122`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 instant rendering**

(a) **Subject identified:** how the server serialises instant-valued fields (the Step 7 site was `hold_expires_at` on a booking and `window_start` on a campaign, but the subject is instant serialisation as a whole).

(b) **Impl paths enumerated (read/grepped):**
- `response.py:12-21` — `iso_ms()` hard-formats `%02d:%02d:%02d.%03dZ`; the single renderer.
- `services/core.py:59,61,79` — `created_at`/`updated_at` set through `iso_ms`.
- `services/core.py:83-93` — `dump()` converts **every** `datetime`-typed row value via `iso_ms`, so the rule is uniform across all entities, not just bookings/campaigns.
- Grepped every `datetime`-typed persisted field: `routes/awards.py:72-73` (`window_start`/`window_end`), `awards.py:313` (`hold_expires_at`), `awards.py:482,533` (`last_settlement_run_at`, incl. its `None` initial value), `routes/governance.py:53,54,56,123` (`effective_at`, `grandfather_until`, `announced_at`), `routes/members.py:52,116` (`status_match_expires_at`, incl. `None`).
- Non-row instant payloads: `routes/ops.py:25` (`current_utc`) and `ops.py:122` (`epoch_at`) — both `iso_ms`. Grepped all `ok(`/`created(`/`ok_list(` callsites that bypass `dump` to confirm these are the only two.
- Input side: `validators.py:98-121` (`parse_dt`/`req_dt`/`opt_dt`) — `Z`/`z` accepted, naive instants read as UTC, offset-bearing instants converted to UTC; this is why an echoed client-supplied `window_start` comes back normalised.
- Exclusion side, to avoid over-claiming: `validators.py:79-95` (`parse_date`) plus `routes/issuers.py:144-145`, `routes/awards.py:164-165,301`, `services/core.py:269`, `routes/governance.py:286`, `routes/awards.py:388` — all date fields are stored/echoed as `YYYY-MM-DD` **strings** (system-generated ledger rows format `today()` into the same string form), so `dump` never touches them. `validators.py:124-137` and `services/core.py:277` — `current_period`/`period`/`posted_period` are `YYYY-MM` strings.

(c) **Wording adjustments made:** (1) Framed the universal claim on "every field whose value is an instant rather than a calendar date" with the field list as illustration, so a field I did not name is still covered correctly by the single `dump`/`iso_ms` path. (2) Added the explicit calendar-date and `YYYY-MM` carve-out so the sentence cannot be read as widening `travel_date`/`activity_date`/`period` into instants. (3) Added "an instant-valued field that has no value is rendered as `null`" after finding four nullable instant fields (`grandfather_until`, `announced_at`, `status_match_expires_at`, `last_settlement_run_at`). (4) Softened an initial "accepted in any ISO 8601 form" to "with or without an explicit offset — bare read as UTC, offset converted to UTC", which is what `parse_dt` actually guarantees, rather than asserting a broader grammar.

## Items with no PRD change
- **Item 1 (envelope double-unwrap, 16 tests / 3 files):** pure test-plumbing defect. `implementation/response.py:42-65` emits exactly the `meta`/`response_type`/`data` envelope that PRD §2.2 already specifies verbatim, for every 2xx path including `/_clock` and `/_ops`. No PRD silence, no mismatch — no edit.

## Step 9: Complete PRD — 2026-09-01T14:46:52.631Z

PRD_COMPLETED.md is complete. All 33 planned edits are applied; no new sections were added and no line was added or removed (every change is an in-paragraph insert or revision).

**Files**
- Source: `workspace/PRD_FINALIZED.md` — 462 lines, 105,252 chars
- Output: `workspace/PRD_COMPLETED.md` — 462 lines, 113,499 chars
- Char delta: **+8,247** (line delta 0)

**Counts:** ambiguity-pins **20**, mismatch-revisions **13** (33 changes across 31 lines)

**Changes**
- §2.1 — insert — ambiguity — list endpoints narrow silently by caller scope instead of 403 (member/issuer collections enumerated; `member_id` filter naming another member still 403) — `routes/members.py:81`, `routes/awards.py:244`, `services/core.py:138`
- §2.2 — insert — ambiguity — `api_request_id` shape is `req_` + exactly 20 chars from A-Z0-9 — `response.py:28`
- §2.2 — insert — ambiguity — `api_request_timestamp` comes from wall clock, never agrees with `current_utc` — `response.py:24,35`
- §2.3 — insert — ambiguity — `limit`/`offset` non-integer or out-of-range → `ERR_INVALID_REQUEST` 400; empty string treated as omitted — `middleware.py:59`
- §2.3 — insert — ambiguity — filters are exact-string, un-validated against enums (no match → empty page, `total_count` 0), empty string treated as absent, applied before scope narrowing — `middleware.py:85`
- §2.4 — insert — mismatch — `created_at`/`updated_at` are wall-clock, not the logical clock, so clock repositioning never reorders listings — `services/core.py:45,66`
- §2.4 — insert — ambiguity — `touch` is idempotent per request: a row modified several times in one request advances `version` by exactly one — `services/core.py:66-73`
- §2.5 — revise — ambiguity — `currency_code` check is structural (any 3 ASCII letters, stored upper-cased), not validated against ISO 4217 — `validators.py:140`
- §2.7 — insert — ambiguity — posting while programme is `OPEN` → `ERR_INVALID_STATE` 409 at rung 8 — `routes/programs.py:118`
- §2.9 — insert — ambiguity — rung 3 judges `memberId`/`member_id` before resolution; booking / ledger row / fraud case ownership is read off the row so rung 5's 404 precedes the scope check — `services/core.py:138`, `routes/awards.py:345`
- §2.9 — revise — ambiguity — rung 4 issuer-scope reads enumerated (issuer, agreement, order via its agreement's `issuer_id`) — `routes/issuers.py:247-269`
- §2.10 — insert — mismatch — a recompute landing on the value already held is not a change (zero-delta counters, unmoved issuer aggregate leave `updated_at`/`version` alone) — `services/core.py:223,234`
- §3.1 — revise — mismatch — partner `iata_code` is only required to be a non-empty string; no two-letter form and no uniqueness enforced — `routes/awards.py:469`
- §3.1 — insert — ambiguity — `windows_recomputed` counts windows visited (not moved); a wholly-past campaign both launches and ends in one sweep — `routes/ops.py:63-70,115-120`
- §3.2 — revise — mismatch — draft stamps `negotiated_by_user_id` with the drafter's `X-User-ID` (not null); price/volume are non-negative integers — `routes/issuers.py:154`
- §3.2 — revise — mismatch — submit *re-stamps* `negotiated_by_user_id`, overwriting the drafter's value; counter `note` validated but persisted nowhere — `routes/issuers.py:199,212`
- §3.2 — insert — ambiguity — revise leaves the two `countered_*` fields standing at the issuer's values — `routes/issuers.py:216`
- §3.2 — revise — mismatch — ratification terminates a `RATIFIED` predecessor as well as an `ACTIVE` one — `routes/issuers.py:258,269`
- §3.4 — revise — mismatch — `external_member_ref` uniqueness not enforced; `cycle_year` accepted as any integer with no range check — `routes/members.py:37,39`
- §3.4 — revise — mismatch — `segments` is optional (defaults 0) even on `FLIGHT_EARN`; stored `base_miles` echoes the caller's input, so on `CARD_SPEND_EARN` it is the ignored value — `routes/members.py:205,242`
- §3.4 — insert — ambiguity — non-earning rows echo any `qualifying_spend_cents`/`segments` supplied while moving no member counter — `routes/members.py:277`
- §3.4 — revise — mismatch — campaign `code` uniqueness not enforced — `routes/awards.py:38,66`
- §3.5 — revise — mismatch — window recompute writes whichever state the fresh load factor names, so `OPEN → CLOSED` and `CLOSED → OPEN` can happen outright; pin field is `capacity_control_state`, `CONSTRAINED` is never pinnable (`ERR_INVALID_STATE`), and a pin writes only the state while still bumping `version` — `routes/awards.py:213-228`, `services/core.py:195`, `calc.py:246`
- §3.5 — insert — ambiguity — ticketing's `REDEEM` row: `activity_date` = logical clock date, `base_miles` = positive `quoted_miles`, `posted_period` snapshot — `routes/awards.py:387`
- §3.5 — insert — ambiguity — refund's `REVERSAL` row picks the most recent matching `REDEEM` by `created_at` (null if none) and mirrors its `activity_date`/`base_miles` — `routes/awards.py:439-442`
- §3.5 — insert — ambiguity — a settlement run returns the updated partner airline row, not a run summary — `routes/awards.py:533-535`
- §3.6 — revise — mismatch — `matched_tier` accepts only `SILVER`/`GOLD`/`PLATINUM` with `trial_days` ≥ 0, so `BASE` is refused at rung 7 with `ERR_INVALID_REQUEST` rather than `ERR_INVALID_STATE` — `routes/members.py:100-101`
- §3.7 — revise — mismatch — case opening freezes (and sets `freeze_applied`) only from `NORMAL`/`WATCH`, watches only from `NORMAL`, and cancels held bookings only when this opening is what froze the member — `routes/governance.py:192-203`
- §3.7 — insert — ambiguity — dismissal `note` is validated but persisted nowhere — `routes/governance.py:312`
- §3.7 — revise — mismatch — substantiation sets `freeze_applied` true unconditionally; the `ADJUSTMENT` row carries the clock's calendar date and positive `clawback_miles` as `base_miles` — `routes/governance.py:280,285-287`
- §3.8 — insert — ambiguity — rollback-cascade campaigns get `version` bumped but `cancellation_reason` left null; `LIVE`/other-channel/other-programme campaigns untouched — `routes/governance.py:146-152`
- §3.9 — insert — ambiguity — only the four listed pairs are permitted; every other pairing including no-ops (`OPEN → OPEN`) → `ERR_INVALID_STATE` 409, and the unposted-lock refusal is also `ERR_INVALID_STATE` — `routes/programs.py:79-94`
- §3.9 — revise — ambiguity — posting row echoes the request's `method` verbatim (null when omitted) alongside `method_applied`, and `period` is not constrained to `current_period` — `routes/programs.py:112,165-166`
