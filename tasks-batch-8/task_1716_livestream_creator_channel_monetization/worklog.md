# Worklog — task_1716_livestream_creator_channel_monetization

## Step 1: Create Task Directory — 2026-08-14T10:22:00.000Z

Task directory `tasks/task_1716_livestream_creator_channel_monetization/` and its `workspace/` subdirectory were pre-created and pre-assigned by the pipeline launcher; Step 1 treated as DONE per instructions. No index scan performed; no other task directory touched.

## Step 3: Copy Shared Files — 2026-08-14T10:23:00.000Z

Copied `./INSTRUCTION.md` → `tasks/task_1716_livestream_creator_channel_monetization/workspace/INSTRUCTION.md` (1424 bytes).

## Step 2: Generate Scaffold — 2026-08-14T11:14:00.000Z

All three artifacts are generated, linted clean, and cross-audited. Summary:

## Files written
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/SCAFFOLD.yaml` — §1.0–§1.7 (no design keys)
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design`

## Counts
| Element | Count |
|---|---|
| Entities | 15 |
| State machines | 15 (cyclic: Payout/ContentStrike/Subscription/Moderator/PerkGrant; parallel dims: Deliverable; compound: Viewer; posture-driven: Channel) |
| Calculations | 10 |
| Validations | 27 priority rows |
| Endpoints | 57 |
| Errors | 30 (all referenced in rules AND exercised by ≥1 design instance) |
| Roles | 6 (Creator entity_backed:Channel, Moderator entity_backed:Moderator, 4 opaque) |
| OCC concurrency rules | 3 (channel settings, tax-form supersede, deliverable reschedule) |
| §1.8 instances | 23 (rules 1,2,3,4,7 carry 3; rules 5,6,8,9 carry 2) |
| §1.9 instances | 45 total: 42 active + 3 excluded_because stubs |
| Structured calls | 552 across both design files |

**Lint verdict (verbatim):** `VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.` Beyond lint, I ran custom audits: placeholder closure (zero unbound `${var}`), grounds resolution, instance-name uniqueness across both files, error-catalog reference+exercise coverage, forbidden-vocabulary scan — all clean.

## Notable design decisions
- **Archetype blend:** ledger reconciliation (primary) + compliance/audit (secondary); flat topology with self-referential `RevenueEvent.reverses_event_id` (chargebacks) — a pattern the spec flags as underrepresented.
- **Hardest calc chain:** payout settlement pins a circular-look evaluation order (withholding → pre-fee snapshot → fee tier keyed on snapshot → fee → net); per-event-then-sum withholding rounding is pinned against the divergent aggregate order (proven with 3×1111-net events: 999 vs 1000); volume rebate is a cliff applied retroactively to a whole settlement month.
- **Dual variants on different domains:** provisional-vs-final revenue recognition (RevenueEvent) and hard-window-vs-decay strike weight (ContentStrike), with the decay variant made observable via `Channel.projected_strike_weight`.
- **Cascades:** deliverable-miss → miss_count → deal BREACHED → clawback event → balance recompute (depth 4); tax expiry → posture → payout HELD (depth 2); strike → SUSPENDED → payout HELD (depth 2) — three distinct triggers.
- **Three interval semantics on three resources:** half-open adjacency (streams), ≥24h buffer with inclusive boundary (simulcast grants), closed-interval boundary-counts (deal category exclusivity).
- **Segregation of duties:** TrustAgent issues / AppealsOfficer resolves, plus a `issued_by_user_id != resolver` self-review block.
- **Logical clock** with the mandated `2026-08-01T00:00:00Z` default; ops-run checkpoint with a pinned 10-step processing order driving settlement, expiry, no-show, breach, renewal cascades.
- **Fixes made during self-review:** RETRY no longer revalidates the threshold (swept funds stay reserved — otherwise 3-retry-cap and invariant tests were unreachable); empty-sweep check ordered before threshold so `ERR_NO_ELIGIBLE_REVENUE` is reachable; corrected the rebate-cliff assert literal (4,625,000); sub-resource GET path params renamed to `{id}` to satisfy lint's FK reverse-reachability form.

## Step 4: Generate PRD — 2026-08-14T11:36:00.000Z

All audits pass. The PRD is complete at `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/workspace/PRD.md`.

## Summary

**PRD line count:** 375 lines

**Section list:**
- §1 Introduction (2 paragraphs — business context + the two design commitments: immediate-consistency ledger and logical clock)
- §2 Global Specifications (9 subsections): 2.1 RBAC, 2.2 API Response Structure, 2.3 Pagination, 2.4 Resource Identity/Timestamps/Path Resolution, 2.5 Logical Clock & Ops Checkpoint, 2.6 Money/Rounding/Ledger Conservation, 2.7 Channel Monetization Posture, 2.8 Optimistic Concurrency Control, 2.9 Validation Order of Precedence
- §3 Business Logic & Workflows (8 subsections, business-domain grouping): 3.1 Onboarding & Tax, 3.2 Revenue & Chargebacks, 3.3 Payouts, 3.4 Tiers/Viewers/Subscriptions/Perks, 3.5 Moderation & Progressive Discipline, 3.6 Strikes & Appeals & Trust Scoring, 3.7 Deals/Deliverables/Disclosure, 3.8 Streams/Simulcast/Consistency
- §4 Endpoint Definitions (57 rows, 4 columns — Method/Path/Description/Authorized Roles; verified all 57 scaffold method+path pairs present)
- §5 Error Code Catalogue (30 rows, 2 columns — verified all 30 id/status pairs present; no trigger conditions)

**Scaffold table placement:**
- §1.0 response_envelope → §2.2 (byte-identical to the fixed source file, verified) + §2.3 (limit 10/1/100, offset 0, `created_at` ascending, meta fields)
- §1.1 entities → scattered across §2.4 (common fields + RevenueEvent append-only exception) and §3.1–3.8 (all 113 field names in backticks)
- §1.2 state machines (15 machines, 80 transitions) → §2.7 (posture machine + cascades) and §3 narratives (all from/to arcs, preconditions with error ids, and side effects)
- §1.2.1 concurrency_rules (3) → §2.8 (all three write endpoints named with `expected_channel_version`/`expected_deliverable_version`, `ERR_STALE_VERSION`/412) and re-stated in 3.1/3.7 workflows
- §1.3 calculations (10) → §2.6–2.7 (ledger, strike weight, trust score) and §3.2–3.8 (rebate cliff, withholding pinned rounding, fee tiers, perk invariant, escalation count, renewal, consistency score, projected decay variant)
- §1.4 validations (26 priorities) → §2.9 explicit ordered ladder (all 26, with mask-order notes: retry cap before fiscal gates, sweep before threshold, window before round cap)
- §1.5 endpoints (57) → §4 table (minimal); side effects rendered in §3
- §1.6 errors (30) → §5 table; all 30 ids also mentioned in §2/§3 prose near their triggers
- §1.7 roles (6) → §2.1 with identity translation (Creator→Channel entity-backed, Moderator→Moderator entity-backed, four opaque roles; Sponsor's `sponsor_ref` business rule)

**Zero-Silence self-audit (Contract 2):** PASS — all 80 transitions expressed with preconditions + error ids + side effects; all 10 calculations reconstructible from prose (constants embedded with unit glosses, e.g. "5,000,000 cents (fifty thousand dollars)", 250 bps rebate cliff, 25/50/100 bps fee tiers); all 26 validation priorities in explicit order; all `applies_to` scopes enumerated (e.g. `ERR_CHANNEL_SUSPENDED` guards exactly five operations); sibling symmetry held (deal CANCEL ×3, payout CANCEL ×2, perk EXPIRED/VOIDED pairs, deliverable reschedule MISSED vs DISPUTED asymmetry from the scaffold preserved); defaults/initial values stated (`MONTHLY`, 10,000 cents, `version` 1, `retry_count` 0, `failure_count` 0, `miss_count` 0, `simulcast`/`exclusive` false).

**Contract 1:** PASS — 113/113 entity fields, 74/74 endpoint inputs (query filters included), 16/16 path params in backticks. Two gaps found by the audit (`perk_kind`, state `REMOVED`) were repaired.

**Contract 3:** PASS — 657 backticked tokens in §3, zero paths/methods; endpoints referenced via state-transition framing (`SCHEDULED` → `HELD`), role+verb ("a `PlatformAdmin` drives settlement"), or capability description. (First audit run appeared to fail catastrophically due to the §2.2 JSON fences corrupting naive regex pairing; after stripping fenced blocks the real result was near-clean.)

**Notable scattering/embedding decisions:** posture machine rendered as a derived rule in §2.7 (which uniquely determines all six arcs) with cascades reinforced in §3.3; the pinned 10-step ops order and 12 response counters live in §2.5 with per-step details cross-referenced into §3; OCC mechanics concentrated in §2.8 and re-anchored in 3.1/3.3/3.7; range constraints (`duration_minutes` 1–10,080, window strictness, `due_at`-in-flight) placed in §2.9 while the workflow parameters live in §3 (≥2-subsection distribution); the projected strike-weight decay translated operator-free as "one-half raised to the power of the strike's age in days divided by thirty". The two difficulty-design index files were never opened.

## Step 5: Generate Unit Tests — 2026-08-14T12:10:00.000Z

Generation complete and fully verified. Summary:

## Output

**`test_helpers/`** (9 files, all under `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/test_helpers/`):
- `types.py` — 15 entity TypedDicts (RevenueEvent correctly carries only `id` + `created_at`, no `updated_at`/`version`), 20 status/field enums, 6-role `UserRole`
- `api_client.py` — `ApiClient(GenericApiClient)` with all 57 PRD endpoints (paths under `/api`)
- `api_errors.py` — 30 `ApiErrorId` values with HTTP map, registered via `set_error_http_status_map`
- `assertions.py` — per-entity `assert_*`, plus `parse_instant`/`assert_instant_equals`, `assert_tier_perk_invariant`, `assert_money_conservation`
- `factories.py` — 15 payload factories, input fields only
- `constants.py` — rebate cliff/fee tiers/withholding/strike weights/caps; canonical operator ids (`trust_nina`, `appeals_omar`, `sponsor_acme`)
- `test_users.py` — `TEST_USERS` + per-instance `make_creator_headers`/`make_moderator_headers` (entity-backed), `make_sponsor_headers` (sponsor_ref identity)
- `fixtures.py` — ~30 composite helpers: verified channels, cleared-event settlement chains, open payouts, ACTIVE deals, ENDED streams, subscription+perk scenarios, strike/appeal drivers
- `__init__.py` — barrel export

**`test_suite/`**: `conftest.py` + 7 test files (`test_01_channels_tax_forms` … `test_07_streams_simulcast`), 4,639 total lines.

## Test counts
- **Queue A (Difficulty): 46 tests** — all 23 instances × exactly 2 tests each
- **Queue B (Corner): 42 tests** — all 42 non-stub instances × 1 test each
- **Total: 88 tests**, collected cleanly by pytest

## Skipped instances
None. Every non-stub instance passed the PRD-first two-condition filter. The 3 `excluded_because:` stubs (`strike_errors_already_exercised_by_difficulty`, `cascading_layers_already_exercised`, `rate_threshold_layers_already_exercised`) were not translated; all their difficulty-instance cross-references resolve.

## Design-tag audit
Every one of the 88 docstrings ends with exactly one `Design: Difficulty/<rule_id>/<name>` or `Design: Corner/<section>/<name>` line; all tags resolve to real instances in the source YAMLs; no untagged/dual-tagged/broken tags.

## PRD-citation pass
All citations survive whitespace-normalized verbatim grep of `PRD.md` (0 failures); citations are rule-bearing sentences (§2.1–§2.9, §3.1–§3.8), not endpoint titles. No skip/xfail markers anywhere.

## Notable translation decisions
1. **`withholding_round_per_event_then_sum`**: the recipe's 3,333-cent payable balance is below the PRD's default 10,000-cent payout threshold, so the payout could never open. I created that channel with `payout_threshold_cents=1000` (a PRD-declared creation input) — the pinned rounding-order assertions (999/2334/23/2311) are unchanged.
2. **Timestamps** are asserted via parsed-instant equality (`assert_instant_equals`), not string equality — the PRD pins the instant, and its three-fractional-digit rendering leaves string formatting open.
3. **`projected_strike_weight`** asserted with `pytest.approx(0.1221, abs=1e-9)` (JSON float vs the PRD's 4-decimal round-half-up rule).
4. **Priority-pair tests** (retry-wrong-state-beats-tax-gate, suspended-beats-overdue) are legitimate because PRD §2.9 states the fixed numbered priority order explicitly — unique derivability holds without scaffold leakage.
5. **`immediate_consistency_after_moderation_action`**: the recipe's optional reversal half was executed (reverse → standing back to `GOOD_STANDING`), both directions asserted.

## Step 6: Generate Implementation — 2026-08-14T12:10:00.000Z

Implementation complete. All work is in `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/workspace/implementation/`.

## File inventory
- `start.sh` — guarded pip install (no-op when flask present) + `exec python3 app.py`, foreground
- `requirements.txt` — flask
- `app.py` — Flask app factory, blueprint registration, envelope-style 404/405/500 handlers; binds `0.0.0.0:$PORT` (default 10000)
- `db.py` — in-memory `Store` (15 entity dicts), logical clock (boots at exactly `2026-08-01T00:00:00Z`), `ops_run_index`, monotonic seq for `created_at` tie-breaks; zero seeding
- `core.py` — `ApiError` + full error catalog, response envelope (`meta.api_request_id`/`api_request_timestamp`, `response_type`, `data`; list meta gains `limit`/`offset`/`total_count`/`has_more`), auth (`X-User-ID`/`X-User-Role`), body/field validators, ISO-8601 UTC 3-fractional-digit rendering, calendar-month math, round-half-up Decimal money
- `domain.py` — all derived fields, posture machine + payout hold/release cascades, viewer standing + ban cascade, serializers for all 15 entities
- `routes/`: `channels.py`, `taxforms.py`, `revenue.py`, `payouts.py`, `community.py` (tiers/viewers/subscriptions/perk-grants), `moderation.py`, `strikes.py`, `deals.py` (deals + deliverables), `streams.py` (streams + simulcast grants), `ops.py` (ops run + clock)

## Endpoints
**57/57** implemented (verified by route-decorator count, matching scaffold `endpoint_count: 57`), with per-action role maps on every `/transition` endpoint and the PRD §2.9 priority ordering (auth → well-formedness → role → existence → ownership → state → suspension → SoD → progressive discipline → temporal gates → OCC → uniqueness → sponsor/moderator/inventory/disclosure gates → fiscal gates).

## State machines (15)
Channel posture (derived: STANDARD/RESTRICTED/SUSPENDED from hard-window strike weight + current tax form, with cause-stamped payout hold/release cascades), TaxForm (SUBMITTED→VERIFIED/REJECTED, EXPIRED via ops; REJECTED→SUBMITTED realized by supersession), RevenueEvent (PENDING→CLEARED at settlement, CLEARED→REVERSED via chargeback), Payout (SCHEDULED/PROCESSING/PAID/FAILED/HELD/CANCELLED, retry cap 3, compensating cancel), Tier, Viewer standing (compound from active actions), Subscription (incl. PAST_DUE 7-day-grace expiry), PerkGrant (incl. past-SLA retry lockout), Moderator (self-accept identity check), ModerationAction, ContentStrike (2-round appeals, UNDER_APPEAL tolls expiry, issuer≠resolver SoD), SponsorshipDeal (incl. breach-at-3-misses clawback), Deliverable (parallel performance × disclosure axes, OCC reschedule), StreamSession (30-min grace, NO_SHOW), SimulcastGrant (24-h buffer rule).

## Calculation modules (10/10)
Dual-variant net recognition (provisional vs final with the 5,000,000-cent / 250bps volume-rebate **cliff** applied per settled month), per-event W8 withholding (round-per-event then sum), pinned payout settlement (withholding → snapshot → pre-fee fee tier 25/50/100bps → fee → net), inclusive threshold gate, hard-window strike weight + trust score + analytics-only 180-day continuous-decay `projected_strike_weight` (4dp half-up, never gates posture), perk inventory invariant (derived from FULFILLED count), consistency score in exact `Fraction` arithmetic rounded once, calendar-clamped monthly renewals, progressive-discipline prior-timeout count, and the payout balance ledger conservation form.

## Clock & ops-run
Logical clock lives in `db.store.clock`, set only via `POST /api/_clock/set_current_utc`, never wall time. `POST /api/ops/run` executes the 10 pinned steps in order (settle → strikes → tax forms → grants → no-shows → misses + 72-h MISSING sweep → perks → renewals/lapses → completions → timeout expiries) and returns all 12 counters including `ops_run_index` (0 at boot, incremented per run) and `payouts_released`.

## Verification
Booted via `bash start.sh` (the evaluator contract), confirmed listening on `0.0.0.0:$PORT` in the foreground via `exec`. Five smoke suites (~120 assertions) covering happy paths, every error-id gate, cascades, OCC, and pagination all pass against fresh boots; a kill/restart cycle confirmed totally fresh state (handles reusable, clock back to boot default). No SQLite, no files, no seeding; `test_suite/`/`test_helpers/` never touched.

## Step 7: Test/Fix Iteration Loop — 2026-08-14T12:30:00.000Z

Ran the 8-round parallel stability sweep (`--isolation per-test-server`). Iteration 1: 5 deterministic failures (83/88 in every round, no flakiness). All fixed in the test layer; the implementation needed no changes. Iteration 2: all 8 rounds 88/88 clean.

Failures and resolutions:
1. `test_02 .../TestChargebacks::test_chargeback_reversal_math` — asserted `balance_payable_cents == 0` after reversal. NOT uniquely derivable: PRD §3.2 ("The original's net leaves the channel's `balance_payable_cents`" => 0) conflicts with PRD §2.6's pinned formula ("sum of final net over the channel's `CLEARED` events — with `CHARGEBACK` nets contributing negative amounts" => -9500 once the original is REVERSED; the reversal paragraph also never pins the chargeback's `platform_fee_bps`, so even the -9500 reading is non-unique). SCAFFOLD.yaml's pinned ledger form and SCAFFOLD_CORNER_DESIGN.yaml's recipe likewise contradict each other. Removed only the post-reversal balance assertion (STEP 1c split); the verbatim-covered assertions (chargeback gross negation, CLEARED status, `reverses_event_id` link, original -> REVERSED, pre-reversal balance 9500) remain.
2. `test_05 .../TestStrikeHardWindowVsProjectedDecay::test_projected_decay_nonzero_where_canonical_is_zero` — `NameError: pytest` (missing `import pytest`); added it. The `pytest.approx(0.1221, abs=1e-9)` assertion itself is verbatim §3.6 (4-decimal half-up decay).
3. `test_06 .../TestDeliverableParallelAxes::test_perform_leaves_disclosure_axis_pending` and `::test_disclose_then_verify_reaches_verified` — `NameError: api`: the shared helper `_performed_undisclosed(self, handle)` called `api.transition_deliverable` without receiving the fixture. Added the `api` parameter and threaded it from both call sites.
4. `test_06 .../TestDealNegotiationAndExclusivity::test_deal_category_exclusivity_closed_interval` — test-setup bug: it proposed+accepted deal2 (VPN, flight [08-20, 09-10]) BEFORE activating deal1 (VPN, [08-05, 08-20]), so deal1's own activation correctly drew `ERR_CATEGORY_EXCLUSIVITY_CONFLICT` from the ACCEPTED sibling (PRD §3.7 counts ACCEPTED siblings and shared boundary instants). Reordered: deal1 reaches ACTIVE first; deal2 is then brought to ACCEPTED and its ACTIVATE is asserted to conflict; deal3 (OTHER) still activates.

## Step 7: Test/Fix Iteration Loop — 2026-08-14T12:35:00.000Z

All 8 parallel rounds pass 88/88. Loop exits.

## Summary

**Iterations run:** 2 (sweep 1: 83/88 in all 8 rounds — 5 deterministic failures, zero flakiness; sweep 2 after fixes: 88/88 in all 8 rounds).

**Tests deleted:** None. No whole test was deleted. One assertion was removed under STEP 1c partial-coverage handling:
- `test_02_revenue_ledger.py::TestChargebacks::test_chargeback_reversal_math` — removed the post-reversal `balance_payable_cents == 0` assertion. **Unique-derivability collapse (conflicting PRD sentences):** PRD §3.2's "The original's net leaves the channel's `balance_payable_cents`" reads as balance 9500 → 0, while PRD §2.6's formula "sum of final net over the channel's `CLEARED` events — with `CHARGEBACK` nets contributing negative amounts" yields −9500 once the original is `REVERSED` and only the chargeback remains `CLEARED` (and the reversal paragraph never pins the chargeback's `platform_fee_bps`, so even −9500 is non-unique). The scaffold itself is split (SCAFFOLD.yaml pinned ledger form vs SCAFFOLD_CORNER_DESIGN.yaml recipe's `== 0 (9500 - 9500)`). The test's verbatim-covered assertions (chargeback `gross_cents == -10000`, `CLEARED`, `reverses_event_id` link, original → `REVERSED`, pre-reversal balance 9500) were kept; the implementation keeps the §2.6-formula behavior.

**Fixes applied to test artifacts:**
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/test_suite/test_05_strikes_appeals.py` — added missing `import pytest` (NameError blocked the verbatim-§3.6 `pytest.approx(0.1221)` decay assertion).
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/test_suite/test_06_sponsorship_deals.py` — `TestDeliverableParallelAxes._performed_undisclosed` now takes the `api` fixture parameter (was calling bare `api` → NameError); both call sites threaded.
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/test_suite/test_06_sponsorship_deals.py` — `test_deal_category_exclusivity_closed_interval` setup reordered: deal2 (same-category VPN, shared boundary instant 2026-08-20) is now brought to `ACCEPTED` only *after* deal1 is `ACTIVE`. The old order made deal1's own ACTIVATE correctly fail — PRD §3.7's exclusivity gate counts `ACCEPTED` siblings and shared boundary instants — so the setup violated the very rule under test.
- `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/test_suite/test_02_revenue_ledger.py` — the single non-derivable balance assertion above.

**Fixes applied to `implementation/`:** None — every failure traced to the test layer; the implementation was PRD-faithful in all five cases (including correctly rejecting the old exclusivity test's setup).

## Step 8: Finalize PRD — 2026-08-14T12:45:00.000Z

Done. `PRD_FINALIZED.md` is written with exactly one scoped edit.

## Summary

**Line counts / delta:** PRD.md 374 lines → PRD_FINALIZED.md 374 lines (0.0% line-count delta); one paragraph revised in place (line 185).

**Changes:**
- **§3.2 (reversal paragraph) — revise** — (1) pinned the reversal-created chargeback's `platform_fee_bps` to equal the original event's `platform_fee_bps` (previously unpinned, which made even the −9500 post-reversal value non-unique); (2) replaced the misleading sentence "The original's net leaves the channel's `balance_payable_cents`, which the subtraction may legitimately drive negative" (which read as balance → 0, conflicting with §2.6) with wording deferring to the §2.6 formula: the original's net exits the payable sum because it is no longer `CLEARED`, and the chargeback's own negative plain-fee net lands in the same sum immediately, so the balance may go negative — impl: `workspace/implementation/routes/revenue.py:98-101` (original → REVERSED; chargeback inherits `e["platform_fee_bps"]`), `workspace/implementation/domain.py:284-306` (plain-fee provisional net; CHARGEBACK born CLEARED), `domain.py:59-64` (balance = sum of net over CLEARED events minus payout reservations).

**No other edits.** The `import pytest` and `api`-fixture items were pure test-code bugs; the exclusivity setup reorder was a test-faithfulness fix against a rule PRD §3.7 already pinned. §2.6's conservation-invariant sentence was left verbatim — it is qualitative and consistent with the formula-derived balance.

**Per-edit pre-edit search log (single edit):**
- **(a) Subject:** attributes of the reversal-created CHARGEBACK event + post-reversal `balance_payable_cents` semantics.
- **(b) Impl paths enumerated and read/grepped:** `routes/revenue.py:77-102` (reverse endpoint, including the chargeability guard at lines 95-97); `domain.py:289-306` (`create_revenue_event`); `domain.py:284-286` (`provisional_net_cents`); `domain.py:59-64` (`balance_payable_cents`); `routes/ops.py:63-80` (month settlement — CHARGEBACKs excluded from month gross, never re-settled); `routes/deals.py:31-39` (`breach_deal` — the parallel chargeback source: fee pinned to 1000 by §3.7, original SPONSORSHIP event *not* flipped). Test-side cross-checks: test_02's kept assertions (chargeback gross −10000, CLEARED, reverses link, original REVERSED, pre-reversal balance 9500); test_06's breach test asserting `balance_payable_cents == -5_400_000` via the same formula while the activation event is still PENDING.
- **(c) Wording adjustment:** scoped the new sentences to "a valid reversal" so the §3.7 breach clawback (which does not flip its original and pins its own fee) is not mis-described; described the balance effect as the §2.6-formula outcome rather than asserting a numeric result, keeping the wording true both when the original settled with the volume rebate (final net ≠ chargeback magnitude) and in the plain case (9500 → −9500).

## Step 9: Complete PRD — 2026-08-14T12:56:00.000Z

Done. `PRD_COMPLETED.md` produced at `/home/ubuntu/github/CodingPRD/tasks/task_1716_livestream_creator_channel_monetization/workspace/PRD_COMPLETED.md` (24 diff hunks, all inline; no new sections).

**Source vs output**: PRD_FINALIZED.md 374 lines / 66,064 chars → PRD_COMPLETED.md 376 lines / 69,671 chars (char-delta +3,607).

**Counts**: 18 ambiguity-pins, 6 mismatch-revisions.

**Mismatch revisions**:
- §2.7 — revise — mismatch — hold cascade fires only on an actual posture change (into `SUSPENDED` from non-`SUSPENDED` always stamps `POSTURE`; `STANDARD`→`RESTRICTED` stamps by cause; unchanged posture holds nothing) — implementation/domain.py:176-187.
- §2.7 — revise — mismatch — `TAX_FORM` release requires only non-`SUSPENDED` posture; the verified form need not be current (impl releases on any verification when posture ≠ SUSPENDED) — implementation/routes/taxforms.py:117-120.
- §3.1 — revise — mismatch — tax-form expiry cascade holds payouts only when the expiry actually moves the channel out of `STANDARD`; already-`RESTRICTED` channels hold nothing — implementation/routes/ops.py:100-108 + domain.py:176-187.
- §3.3 — revise — mismatch — holds paragraph: trigger is "recomputation actually moves the channel out of `STANDARD`", not "form becoming EXPIRED or REJECTED" unconditionally — domain.py:176-187.
- §3.3 — revise — mismatch — release sentence drops the "current form must be `VERIFIED`" condition for `TAX_FORM` releases — taxforms.py:119-120.
- §3.4 — revise — mismatch — `lifetime_spend_cents` accumulates paid subscription-cycle gross only ("and tips" removed; revenue events carry no viewer reference) — implementation/routes/community.py:174-190.

**Ambiguity pins**:
- §2.1 — insert — ambiguity — read/list endpoints apply no ownership check; ownership bites only on writes whose narratives call for it — routes/*.py GET handlers (e.g., channels.py:43-50).
- §2.2 — insert — ambiguity — `api_request_timestamp` is rendered from the logical clock — core.py:58-62.
- §2.3 — insert — ambiguity — non-integer/out-of-range `limit`/`offset` → `ERR_INVALID_REQUEST`, `offset` ≥ 0; `created_at` ties broken by creation order — core.py:252-279.
- §2.5 step 6 — insert — ambiguity — same step also forces `PERFORMED`-and-`PENDING` disclosures >72h past `performed_at` to `MISSING`, not counted in `deliverables_missed` — ops.py:125-142.
- §2.5 — insert — ambiguity — reported `ops_run_index` is post-increment (first run reports 1) — ops.py:195-197.
- §2.9 item 2 — insert — ambiguity — remaining range rules: `revenue_share_bps` 0–10,000; `flight_end` at or after `flight_start`; non-negative `payout_threshold_cents`/`monthly_price_cents`/`perk_inventory_total`/`total_value_cents`/`required_deliverable_count`/`peak_viewers`/`avg_viewers`; deliverable flight check evaluates after deal/stream existence, before ownership/state — deals.py:56-57,185-197,326-328; community.py:31-33; channels.py:26,58; streams.py:95-96.
- §3.2 — insert — ambiguity — direct `CHARGEBACK` ingestion validates only that `reverses_event_id` exists in the same channel; no kind/status constraint on the target — revenue.py:42-45.
- §3.2 — insert — ambiguity — reversal requires a non-empty `reason`; the created chargeback stamps `occurred_at` from the clock — revenue.py:81-83,99-101.
- §3.3 — insert — ambiguity — each revenue event carries a `withholding_cents` field (zero at ingestion, stamped per-event at sweep) — domain.py:302,349-351.
- §3.3 — insert — ambiguity — cancelling a `HELD` payout clears `hold_reason` to `NONE` and resets swept events' `withholding_cents` to zero — payouts.py:126-128, domain.py:356-364.
- §3.4 — insert — ambiguity — cycle-1/renewal `SUBSCRIPTION` events stamp `occurred_at` from the clock; initial `current_period_end` uses the same clamped month arithmetic as renewal — community.py:160-179.
- §3.4 — insert — ambiguity — `RECOVER` changes only `sub_status`; `current_period_end`/`cycles_paid` untouched — community.py:262-269.
- §3.5 — insert — ambiguity — a `Moderator` caller whose `X-User-ID` names no moderator of the channel → `ERR_NOT_FOUND` — moderation.py:147-149.
- §3.5 — insert — ambiguity — moderation-action reversal requires a non-empty `reason` — moderation.py:203-205.
- §3.6 — insert — ambiguity — `projected_strike_weight` 180-day window measured from each strike's `issued_at` — domain.py:97-104.
- §3.7 — insert — ambiguity — disclosure at exactly the deadline counts as `DISCLOSED_ON_TIME`; the 72h `MISSING` sweep applies to `PERFORMED` deliverables — deals.py:285-288, ops.py:137-142.
- §3.7 — insert — ambiguity — breach chargeback stamps `occurred_at` from the clock; the activation `SPONSORSHIP` event stays `CLEARED` (not flipped to `REVERSED`) — deals.py:31-39.
- §3.7 — insert — ambiguity — reschedule also clears `disclosure_deadline` — deals.py:340.
- §3.8 — insert — ambiguity — consistency-score window is inclusive at both ends — domain.py:122-125.
- §4 — insert — ambiguity — undefined paths/unsupported methods → `ERR_NOT_FOUND` (404); any other unexpected failure → `ERR_INVALID_REQUEST` (400) — app.py:28-38.
