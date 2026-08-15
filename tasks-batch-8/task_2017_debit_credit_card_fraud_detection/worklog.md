# Worklog — task_2017_debit_credit_card_fraud_detection

## Step 1: Create task directory — 2026-08-15T07:03:00.000Z

Directory `tasks/task_2017_debit_credit_card_fraud_detection/` and `workspace/` pre-created by the calling pipeline (Step 1 marked as already done).

## Step 2: Generate scaffold — 2026-08-15T08:02:40.919Z

Done. All three scaffold artifacts generated for task 2017 (Debit & Credit Card Fraud Detection Operations), with a clean lint verdict.

## Files written

- `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/SCAFFOLD.yaml` (96 KB) — §1.0–§1.7 only
- `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/SCAFFOLD_DIFFICULTY_DESIGN.yaml` (96 KB) — single top-level key `scaffold_difficulty_design`
- `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/SCAFFOLD_CORNER_DESIGN.yaml` (124 KB) — single top-level key `scaffold_corner_design`

No sibling task directories were inspected; the design is purely from the scenario text plus the skill spec.

## Design summary

**Profile**: compliance/audit (primary) + posture-driven gating (secondary); flat topology (14 peer entities, FK-linked); cyclic state-machine shape; **segregation_of_duties** role model (rule drafter ≠ activator; loss booker ≠ recovery filer — enforced by user id, not just role); immediate consistency. Layers: rate/threshold triggers, dual-variant calculation, optimistic concurrency (one true-race OCC rule on `RuleSet.version` per the §1.2.1 filter), cascading side effects.

**Surface**: 14 entities, 67 endpoints, 30 error codes, 10 calculations, 14 state machines, 6 roles (incl. `Cardholder` entity-backed by Account, `NetworkGateway` for auth intake). Logical clock endpoint with the mandated `2026-08-01T00:00:00Z` default drives all lazy time transitions (alert 72h expiry, reissue auto-approve at due date, notice expiry, rolling-loss window).

**Difficulty depth (§1.8 — 24 instances, all 9 rules)**:
- 3 dual-variant calcs in distinct domains: shadow rescore under superseding ruleset (75/REVIEW vs 85/DECLINE, same data), loss provisional-vs-final (11502 vs 11000), FP-rate review-basis vs decline-basis (5000 vs 10000 bp)
- 3 combinatorial modes: (a) 5-input nonlinear scoring with tier step at exactly 100000, (b) pinned per-line-round-then-sum loss provision (23002, not 23001), (c) alert-priority ↔ risk-tier circular dependency with pinned evaluation order (25 vs 125 vs wrong-order 225)
- 3 non-linear machines on different entities (card block/unblock cycle × parallel fraud_flag dimension; alert reopen loop with counter cap and disposition flip; chargeback WON/LOST fork with opposite ledger effects)
- Depth-4 cascade (event confirm → card COMPROMISED → account tier HIGH → alert priority 25→225) and depth-3 recovery cascade (PAID → outstanding 0 → FULLY_RECOVERED → tier HIGH→LOW)
- 3 priority conflicts on distinct category pairs (state>fiscal, state>safety, temporal>fiscal); 3 boundary checks on distinct metrics/endpoints (score ==100 declines; credit equality ≤ allowed; contact gap 59 min fails / 60 passes); 3 cross-entity state deps on distinct pairs; 2 overlap rules with different interval semantics (half-open travel notices per card vs 60-minute contact buffer per account); 2 compensating invariants on different conserved quantities (credit ledger, loss outstanding)

**Corner coverage (§1.9 — 59 instances, 55 active + 4 excluded_because stubs)**: all nine claim-extraction-guide sections, with every one of the 30 error codes exercised by at least one test (verified mechanically) and all stubs referencing real §1.8 instances.

## Lint verdict (verbatim)

```
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```
(67 endpoints, 14 entities, 24 §1.8 + 55 §1.9 instances, 777 calls scanned, zero violations.)

Also verified post-lint: zero duplicate instance names across the union of both design files, no forbidden race vocabulary anywhere, and call-by-call replay was applied while drafting (contact-gap clock bumps between same-account contacts, claim-before-contact assignment pinning, APPROVE-only chargeback prerequisites, tolerance/window literals all hand-computed: e.g. tolerance 1150 on provisional 11502, finalize deadline 2026-08-31T00:00:00Z, due_at 2026-08-07T12:00:00Z).

## Step 3: Copy shared files — 2026-08-15T08:03:08.146Z

Copied `./INSTRUCTION.md` → `tasks/task_2017_debit_credit_card_fraud_detection/workspace/INSTRUCTION.md`.

## Step 4: Generate PRD — 2026-08-15T08:12:00.000Z

Done. The PRD is written to `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/workspace/PRD.md` (300 lines), generated solely from `SCAFFOLD.yaml` — the two forbidden design files were never opened.

## Summary

**Document structure** (domain-derived, not template-copied):
- §1 Introduction — 2 paragraphs from the false-positive/fraud-loss tension angle
- §2 Global Specifications — 11 subsections: RBAC with per-role identity translation, verbatim §2.2, pagination, common resource properties, the logical clock + lazy transitions, validation priority order, nested retrieval/reverse reachability, monetary precision with the pinned rounding-order example (11502 vs 11501), OCC, segregation of duties, and the INV-CREDIT/INV-LOSS ledger invariants
- §3 Business Logic — 11 subsections organized by workflow: accounts/cards/risk tiers, ruleset drafting/activation, realtime + shadow scoring, alert queue/priority, verification contact/resolution, compromise cascade/reissue, chargebacks, loss/recovery ledger, ring detection, travel notices, ruleset metrics
- §4 Endpoint table — 67 rows, 4 columns (Method/Path/Description/Roles), all paths verified against scaffold
- §5 Error catalogue — 30 rows, 2 columns, all statuses match scaffold

**Hard Contract Reports:**

```
Field coverage check:
- entities[].fields: 103 required, 103 present, 0 missing
- endpoints[].input (request_body + query params): 75 required, 75 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 11 checked, 11 expressed (full priority order + masking rule in §2.6, plus two endpoint-local orderings: chargeback state-beats-fiscal, finalize temporal-beats-fiscal), 0 missing
- concurrency_rules[] OCC rejections: 1 checked, 1 expressed (PUT ruleset + expected_ruleset_version + ERR_STALE_VERSION/412, framed purely in stale-version terms), 0 missing
- state_machines[].transitions: 38 checked across 14 machines, 38 expressed (all from/to states, preconditions paired with error IDs, all cascade side effects including the 4-link compromise cascade, ring-dismiss compensation, INV-LOSS reversal semantics), 0 missing
- calculations[]: 9 checked, 9 expressed (scoring incl. scope resolution + travel suppression + inclusive decline boundary, loss provision with pinned per-line-then-sum rounding and the 11502/11501 example, risk tier thresholds, alert priority 3-step pinned order + one-way escalation, rolling 90d loss, credit balance, exposure window match with deterministic creation order, reissue exposure, false-positive monitor with both bases + zero-denominator rule, loss outstanding), 0 missing
- validations[] conditions: 30 error IDs checked, all 30 matchable to trigger prose in §2/§3, 0 missing
- endpoints[].side_effects / applies_to: 67 endpoints checked, side effects expressed (REVIEW creates exactly one alert, card-blocked bypass still records with 201, lazy auto-approve/auto-close, replacement cascade cancels travel notices, etc.), 0 missing
- entities[].fields[] structured content: defaults, nullability, and enum membership reconstructible from prose (e.g., block_reason null when ACTIVE, fraud_credit_cents default 0, reopen_count default 0, currency default USD, high_risk_countries default empty, 25 MANUAL band / 49 cap), 0 missing
- sibling-branch symmetry: ring confirm/dismiss pair, WON/LOST chargeback resolution pair, approve/decline reissue pair, realtime/shadow scoring variants, review/decline FP-rate bases — all rendered with equal density, 0 asymmetric
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 587
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

Additional quality gates verified: §2.2 byte-identical to the canonical source file; zero pseudocode operators (`>=`, `==`, `+=`, `->`) in prose outside backticks; zero fuzzy/approximating words; all state and enum values present as exact UPPERCASE strings; logical-clock default `2026-08-01T00:00:00Z` stated.

## Step 5: Generate unit tests — 2026-08-15T08:46:00.000Z

Generation complete for task 2017. Summary:

## What was generated

**`test_helpers/` (9 files)** under `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/test_helpers/`:
- `types.py` — 14 entity TypedDicts (all carry full common fields per PRD §2.4) + 20 status/role enums
- `api_client.py` — `ApiClient(GenericApiClient)` with one method per PRD endpoint (44 methods incl. `/_clock/set_current_utc`)
- `api_errors.py` — all 30 `ApiErrorId` values with the PRD §5 HTTP status map, registered via `set_error_http_status_map`
- `assertions.py`, `factories.py`, `constants.py` (RS-STD payload, tier points, thresholds), `test_users.py` (opaque shared constants + `make_cardholder_headers(account.id)` per-instance builder for the entity-backed Cardholder role), `fixtures.py` (composite setups: `setup_account_with_card_and_ruleset`, `setup_confirmed_fraud_txn`, `create_booked_loss`/`create_finalized_loss`/`create_accepted_filing`, `create_and_confirm_event`, `get_decision_for_card`)
- `__init__.py` barrel export

**`test_suite/` (14 files, 113 test functions)** under `.../test_suite/`, organized by concern: accounts/envelope, scoring, shadow-rescore/metrics, ruleset lifecycle (incl. OCC), card lifecycle, alerts, contacts, compromise events, travel notices, chargebacks, losses/recoveries, rings, RBAC.

## Coverage audit (machine-checked)

- **Queue A (Difficulty):** all 24 instances have ≥2 tests each — every test docstring ends with `Design: Difficulty/<rule_id>/<instance.name>`.
- **Queue B (Corner):** all 75 non-stub instances have ≥1 test with `Design: Corner/<section>/<instance.name>`; the 4 `excluded_because:` stubs emit no tests and their difficulty-instance cross-references all resolve.
- **C4 tag audit:** exactly one Design tag per test, zero untagged, zero tags pointing to non-existent instances, zero freelance tests.
- **C1 verbatim sweep:** all 113 docstring PRD citations survive literal grep of `PRD.md` (after repairing 9 wrapped/paraphrased quotes).
- **No skips:** no `pytest.mark.skip`/`skipif`/`xfail` anywhere; no scaffold references in comments.
- All files compile; every `test_suite` import resolves against `test_helpers`.

## Key adjudication decisions

- **Priority-pair tests** (`state_beats_fiscal`, `state_beats_safety`, `temporal_beats_fiscal`) were kept (not skipped under the `validation-priority` silence pattern) because PRD §2.6 explicitly states the ordering ("a state error beats a fiscal cap"; §3.8 "the temporal check, evaluated before the fiscal one").
- **Two-reader passes:** tests assert only values the PRD uniquely pins (e.g., priority 25/125 from the §3.4 pinned three-step order; 11502/23002 provisional amounts from the §2.8 pinned rounding order; `due_at == confirmed_at + 5 days`).
- The 90-day rolling-loss boundary test uses the PRD's "inclusive 90-day window" wording; contact-gap uses "at least 60 minutes … strictly inside that gap is rejected"; decline threshold uses "(an inclusive boundary)".

One environment note: tests assume `POST /fraudops/fraud-alerts` accepts `auth_transaction_id` optionally and that the logical clock endpoint accepts `to_iso8601` — both per PRD. No tests were skipped for PRD silence; every design-index instance had verbatim PRD coverage.

## Step 6: Generate implementation — 2026-08-15T08:35:00.000Z

All files are in place. Final summary:

## Implementation Complete

Generated a complete Python + Flask REST API server at `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/workspace/implementation/`.

### Architecture
- **`start.sh`** — guarded dependency install (no-op if flask already present), `exec python3 app.py`, binds `0.0.0.0:$PORT` (default 10000)
- **`app.py`** — Flask app, registers 14 blueprints, error handlers
- **`db.py`** — in-memory stores (empty on boot, no seeding), logical clock pinned at `2026-08-01T00:00:00Z`
- **`errors.py`** — all 30 error IDs with exact HTTP statuses from scaffold §1.6
- **`response.py`** — envelope `{meta: {api_request_id, api_request_timestamp, ...pagination}, response_type, data}` exactly per §2.2
- **`middleware.py`** — X-User-ID / X-User-Role auth, role gating, id/timestamp/version stamping
- **`services/domain.py`** — serializers, derived-field recompute (credit_balance/open_alert_count/rolling_90d_loss/risk_tier), lazy time-based transitions (alert SLA expiry, reissue auto-approve, travel-notice expiry, event auto-close), scoring formula, per-line-half-up loss provisional
- **`routes/*.py`** — 14 route modules covering all 46 endpoints

### Key fidelity details implemented
- Logical clock via `POST /_clock/set_current_utc`; never falls back to wall clock
- OCC on `PUT /fraudops/rule-sets/{id}` via `expected_ruleset_version` → ERR_STALE_VERSION 412
- Threshold order `review_threshold < decline_threshold` → ERR_THRESHOLD_ORDER_INVALID 422
- Authorization scoring with amount tiers, channel weights, cross-border × high_risk_multiplier, watch/compromised flag weights, travel suppression; blocked card → DECLINE/CARD_BLOCKED with null score/ruleset, HTTP 201, no alert
- Shadow rescore at read time under currently-ACTIVE ruleset
- Compromise cascade (4 links) with deterministic ReissueDecision creation order (earliest txn scored_at ASC, then card created_at ASC)
- Ring detect (≥3 accounts, ≥2 APPROVE txns each); confirm→WATCH; dismiss-from-CONFIRMED compensates only the cards that ring raised
- Reissue decision: APPROVE mints replacement (WATCH, replaces_card_id); DECLINE downgrades COMPROMISED→WATCH; >50000 exposure decline requires FraudOpsManager; AUTO_APPROVED at due_at lazily
- Alert queue priority: TIER_POINTS[acct tier excluding new alert] + band_points (25 MANUAL / min(49, max(0, score−review_threshold)) SCORING_REVIEW); OPEN list ordered priority DESC, created_at ASC; one-way escalation to ≥200+band on HIGH-tier transitions
- Reopen: cap reopen_count < 2 → ERR_REOPEN_LIMIT_EXCEEDED; 30-day window from resolved_at → ERR_INVALID_STATE
- Chargeback state machine with ERR_CHARGEBACK_INVALID_STATE; duplicate-credit cap with equality allowed → ERR_DUPLICATE_CREDIT 422
- Loss: per-line `round_half_up(amount * (1 − RECOVERY_RATE[network]))` then sum (verified the pinned 11502 example: VISA 10001→5501 + MASTERCARD 10001→6001); tolerance = round_half_up(prov × 0.10) = 1150
- Recovery filing segregation of duties (filer ≠ booked_by_user_id); PAID/REVERSED cascade recomputes outstanding and FINALIZED/PARTIALLY_RECOVERED/FULLY_RECOVERED
- Contact 60-minute per-account gap → ERR_CONTACT_TOO_SOON
- Alert resolution requires COMPLETED contact with matching outcome and contacted_at strictly after last resolution → ERR_CONTACT_REQUIRED
- Cardholder respond path creates COMPLETED IN_APP contact (created_by SYSTEM) and resolves even from OPEN
- Cross-analyst custody enforced as ERR_FORBIDDEN_ROLE
- Cardholder ownership via X-User-ID == Account.id → ERR_NOT_RESOURCE_OWNER
- All timestamps ISO-8601 UTC with 3 fractional digits; all resources carry id/created_at/updated_at/version (version increments on every mutation)

### Verified end-to-end
- Smoke tests passing for: auth, RBAC, ownership, account suspend/reinstate gating, card block/unblock with ERR_CARD_COMPROMISED, ruleset lifecycle (create→activate→supersede→retire), scoring (base/amount/channel/cross-border/high-risk/travel-suppression/flag), alert full lifecycle (create→claim→contact→complete→resolve→reopen), SLA expiry, cardholder respond, compromise cascade with reissue (manual and AUTO_APPROVED), ring detection/confirmation/dismissal compensation, chargeback duplicate-credit cap and state machine, loss provisional/tolerance/finalize/write-off, recovery filing mark-outcome with PAID/REVERSED restoring outstanding, shadow rescore under superseding ruleset, ruleset metrics with missed_declines_under_current.

### Boot contract
`bash start.sh` from `implementation/` boots cleanly from a fresh process with empty stores, binds `0.0.0.0:$PORT`, responds within seconds, and uses `exec` so the harness's per-test kill/relaunch cycle propagates signals correctly.

## Step 7: Run tests and iterate — 2026-08-15T09:04:04.150Z

The 8-round sweep is fully clean. Final report:

## Summary

**Iterations run:** 2 (baseline sweep → fixes → verification sweep).

**Baseline:** 105/113 passed in every round; the same 8 tests failed deterministically in all 8 rounds (no flakiness).

**Final:** all 8 rounds 113/113 passed — clean parallel sweep.

**Tests deleted:** none. Every failure traced to either a test artifact violating PRD preconditions / asserting a PRD-silent format, or one genuine implementation gap.

**Fixes applied to `test_helpers/`:**
- `assertions.py` — added `parse_iso8601` helper for value-based (instant) timestamp comparison.
- `fixtures.py::setup_confirmed_fraud_txn` — when the intake scores REVIEW, the auto-created SCORING_REVIEW alert (PRD §3.3: "A `REVIEW` decision creates exactly one `FraudAlert`") is now also resolved FRAUD (claim → contact with a +61-min clock bump for the §3.5 per-account gap → resolve). Previously the dangling OPEN alert forced `risk_tier` MEDIUM per §3.1, which broke `test_11::test_full_payment_cascades_to_fully_recovered_and_low_tier`.

**Fixes applied to `test_suite/`:**
- `test_05::test_reissue_auto_approve_after_due_date`, `test_06::test_alert_created_in_open_with_initial_priority`, `test_08::test_confirm_flags_in_window_cards_and_spawns_decisions` — STEP 1c partial coverage: PRD pins the *values* ("creation plus 72 hours", "confirmed_at plus 5 days") but scopes "three fractional digits" to `created_at`/`updated_at` (§2.4) and `api_request_timestamp` (§2.2), leaving the string format of computed timestamps underdetermined (implementation emits `.000Z`, tests demanded no-fraction). Assertions now compare parsed instants instead of exact strings.
- `test_08::_setup_cascade` — the pre-existing manual alert was created before a clock excursion to 2026-08-10, which tripped PRD §2.5 lazy SLA expiry (72h) and terminally EXPIRED it before the escalation assertion; alert creation moved after the clock returns to 2026-08-02T12:00.
- `test_12::TestRingDetectBelowMinimumAccounts._seed_accounts` — authorizations were posted before any ACTIVE ruleset existed (correctly rejected with ERR_NO_ACTIVE_RULESET per §3.3); `create_active_ruleset()` moved ahead of the first intake.

**Fixes applied to `implementation/`:**
- `services/domain.py::apply_time_based_transitions` — recompute every account's derived fields on clock advance: `rolling_90d_loss_cents`/`risk_tier` are defined relative to "the current logical time" (§2.11), so a pure clock advance must refresh them (fixes `test_11::test_loss_drops_out_at_91_days`).
- `routes/accounts.py` — `get_account`/`list_accounts` recompute derived fields before filtering/serializing, same §2.11 justification. Recompute only touches the row when a value changes (§2.4: derived-field recomputations count as mutations).

Environment note: the first post-fix sweep was killed by a host-level timeout while sibling pipelines saturated the box; it was relaunched detached (`setsid` + completion marker) and completed cleanly with 8/8 rounds passing.

## Step 8: Finalize PRD — 2026-08-15T09:12:00.000Z

Done. `PRD_FINALIZED.md` is written at `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/workspace/PRD_FINALIZED.md` with three in-place paragraph edits (4 logical changes), all traceable to `<step_7_diff>` items.

## Size delta
- PRD.md: 300 lines / 54,260 chars; PRD_FINALIZED.md: 300 lines / 55,542 chars — +1,282 chars, **+2.36%**, 0 line-count change (edits are inline within existing paragraphs; no new sections).

## Changes (one bullet per change)
- **§2.4** — insert — pins that the three-fractional-digit ISO 8601 UTC format applies to *every* server-generated timestamp field, naming the §2.5 stamps (`scored_at`, `contacted_at`, `booked_at`, `finalized_at`, `confirmed_at`, `resolved_at`, `decided_at`) and computed deadlines (`sla_expires_at`, `due_at`) — `implementation/db.py:26-27` (`_now_iso`), `implementation/services/domain.py:20-21` (`_iso`), stamps at `routes/auth_transactions.py:47`, `routes/verification_contacts.py:59`, `routes/loss_entries.py:107,147`, `routes/compromised_card_events.py:98,152`, `routes/fraud_alerts.py:88,244`, `routes/reissue_decisions.py:67`, `services/domain.py:427,645`. (Covers Step 7 test_suite fixes to test_05/test_06/test_08 and the `parse_iso8601` helper.)
- **§2.4** — revise — appended "a recomputation that produces no new value writes nothing back and leaves `updated_at` and `version` untouched" to the derived-field-mutation sentence — `implementation/services/domain.py:348-359` (account recompute touches only on change; same pattern at `domain.py:692-717` loss outstanding, `domain.py:370-372` alert escalation). (Covers the "recompute only touches the row when a value changes" half of the `routes/accounts.py` fix.)
- **§2.5** — insert — the clock-advance pass additionally recomputes every account's derived fields, since the §2.11 rolling window ends at the current logical time — `implementation/services/domain.py:386-391` (`apply_time_based_transitions`, invoked only from `routes/clock.py:25`). (Covers the `domain.py` fix for `test_11::test_loss_drops_out_at_91_days`.)
- **§2.11** — insert — account read endpoints refresh derived fields before responding: single-account GET recomputes the four derived fields; list endpoint recomputes every account before applying `status`/`risk_tier` filters — `implementation/routes/accounts.py:54-55,77`. (Covers the `routes/accounts.py` fix.)

Step 7 items with **no PRD edit** (already pinned or pure fixture bugs): `fixtures.py::setup_confirmed_fraud_txn` (§3.3 already pins exactly-one-alert on REVIEW; §3.1 pins tier), `test_08::_setup_cascade` clock excursion (§2.5 lazy expiry already pinned), `test_12::_seed_accounts` (§3.3 `ERR_NO_ACTIVE_RULESET` already pinned).

## Per-edit pre-edit search log
1. **§2.4 timestamp-format insert.** (a) Subject: string format of server-emitted timestamps. (b) Enumerated/read: every serializer in `services/domain.py:36-280`; all write sites via grep — `db._now_iso`/`get_clock_iso` (3-frac, millisecond) for created/updated (`middleware.py:44-57`), the seven §2.5 stamps, clock-endpoint `current_utc` (`routes/clock.py:26`); `domain._iso` (3-frac) for `sla_expires_at` (`domain.py:645`) and `due_at` (`compromised_card_events.py:152`); user-supplied fields stored verbatim — `window_start`/`window_end` (`compromised_card_events.py:53-54`, `fraud_rings.py:57-58`), `start_date`/`end_date` (`travel_notices.py:68-69`); `response.py:17-19` meta timestamp (out of diff scope, deliberately not covered). (c) Wording scoped to "server-generated timestamp field on a resource" and lists only fields verified 3-frac — client-supplied window/date fields are left unmentioned so no claim about them is made; `api_request_timestamp` excluded (already pinned in §2.2, and wall-clock in impl — out of Step 7 scope).
2. **§2.4 no-change-recompute clause.** (a) Subject: when a derived-field recomputation advances `updated_at`/`version`. (b) Enumerated/read: `domain.py:287-359` (`_recompute_account` — touch only when changed), `domain.py:680-718` (`recompute_loss_outstanding` — same), `domain.py:362-372` (`_escalate_open_alerts` — same); all 15 `_recompute_account` callsites grep-verified across `routes/` and `services/`. (c) Phrased as the symmetric negative of the existing "write back" sentence ("produces no new value writes nothing back"), so it holds uniformly for account, loss, and alert-escalation recomputes rather than only the Step 7 site.
3. **§2.5 clock-advance recompute insert.** (a) Subject: what a clock advance applies beyond the three lazy transitions. (b) Enumerated/read: `domain.py:379-391` (full pass: alert expiry, reissue auto-approve, notice expiry, event auto-close, all-account recompute), `routes/clock.py:25-26` (sole caller), plus §3.6's already-pinned "event auto-close … on clock advances" and the `_recompute_account` window logic at `domain.py:318-330` (inclusive `[now-90d, now]`). (c) Used additive wording ("additionally recomputes") so the existing lazy-transition list is not redefined; scoped the observable effect to `rolling_90d_loss_cents`/`risk_tier` since `credit_balance_cents`/`open_alert_count` cannot change from a clock advance alone (recomputing them is a no-op), avoiding any claim that would mis-describe the other two fields.
4. **§2.11 account-read refresh insert.** (a) Subject: derived-field freshness on account reads. (b) Enumerated/read: every `ser_account` callsite — `routes/accounts.py:43` (create: fresh zeros, no staleness possible), `:63` (list, recompute-all at :54-55 before filters at :57-60), `:78` (get, recompute at :77), `:91,:104` (suspend/reinstate: no recompute, but stored values cannot be stale because the only time-mutation path — `routes/clock.py:25` — recomputes all accounts, and every alert/card/loss/chargeback/ring write path calls `_recompute_account`, verified by grep across `routes/*.py`). (c) Wording names "the single-account GET" and "the list endpoint" explicitly and closes with "the values returned by these endpoints" rather than a universal "every response containing an account is refreshed", so suspend/reinstate (which serialize without recomputing) are not mis-described.

## Step 9: Complete PRD — 2026-08-15T09:33:00.000Z

Done. `/home/ubuntu/github/CodingPRD/tasks/task_2017_debit_credit_card_fraud_detection/workspace/PRD_COMPLETED.md` written (copy of PRD_FINALIZED.md + minimal inline edits; no new sections).

## File stats
- Source: `PRD_FINALIZED.md` — 300 lines / 55,705 chars → `PRD_COMPLETED.md` — 302 lines / 62,594 chars (**+2 lines, +6,889 chars**; 27 paragraphs revised in place, 1 short paragraph inserted in §2.2).

## Counts
- Ambiguity-pins: 20
- Mismatch-revisions: 9 (§2.5 wall-clock blanket, §2.6 priority 5/6 swap + custody/rationale placement, §3.1 operator block_reason, §3.2 tunable `scope`, §3.3 multiplier truncation, §3.4 queue tie-break, §3.5 reopen boundary, §3.8 claimed_cents error code, §3.10 stale-ACTIVE overlap)

## Changes (section — insert|revise — ambiguity|mismatch — what — impl ref)
- §2.2 — revise — ambiguity — `api_request_timestamp` pinned as wall-clock UTC, lone exception to §2.5 — implementation/response.py:17-19
- §2.2 — insert — ambiguity — unknown route/method → `ERR_NOT_FOUND` 404; unexpected failure → `ERR_INVALID_REQUEST` 500; malformed JSON body treated as `{}` — implementation/app.py:51-71, all routes' `request.get_json(silent=True) or {}`
- §2.3 — revise — ambiguity — limit/offset clamped (1..100, ≥0), non-integer falls back to defaults — implementation/services/domain.py:770-785
- §2.3 — revise — ambiguity — list ties on `created_at` broken by `id` ascending — e.g. implementation/routes/accounts.py:56
- §2.4 — revise — ambiguity — `version` starts at 1 — implementation/middleware.py:44-51
- §2.5 — revise — mismatch — "never wall-clock" scoped to domain timestamps (envelope excepted) — implementation/response.py:17-19
- §2.5 — insert — ambiguity — clock set accepts any well-formed ISO instant (backward allowed), missing/malformed → `ERR_INVALID_REQUEST`, responds 200 `{"current_utc": ...}` — implementation/routes/clock.py:14-26
- §2.5 — insert — mismatch — event auto-close also evaluated on event reads; travel-notice creation does not run the lazy pass — implementation/routes/compromised_card_events.py:84, implementation/routes/travel_notices.py:53-62
- §2.6 — revise — mismatch — request shape (new priority 5) now precedes body foreign-reference resolution (6); custody removed from priority-2 gate; `rationale` removed from shape list; `ERR_RING_THRESHOLD_NOT_MET` added to priority 7 — all route files (e.g. auth_transactions.py:28-45)
- §2.6 — insert — mismatch — four refinement rules: custody placement per endpoint (resolve/complete: after shape, before state; contact-create: after state); selector enums before state but action params after it (decide/rationale, PAID/paid_cents, finalize/final_amount_cents, PUT version→DRAFT→fields); resolve checks `ERR_CONTACT_REQUIRED` before `fraud_credit_cents`; manual-alert and travel-notice ref-resolution interleavings; uniqueness guards (account_number/pan_token/network_reference) fire after refs, before state; coded strings validated for presence/type only — routes/fraud_alerts.py:200-216, verification_contacts.py:19-113, reissue_decisions.py:50-63, recovery_filings.py:98-112, loss_entries.py:121-125, rule_sets.py:155-173
- §2.7 — revise — ambiguity — cards also filter by `card_status`/`fraud_flag`; events filter by `event_status`/`network_source` — routes/cards.py:69, compromised_card_events.py:69
- §3.1 — revise — ambiguity — suspend/reinstate from wrong state → `ERR_INVALID_STATE`; `account_status` consulted only by card/travel-notice creation — routes/accounts.py:87-101, cards.py:45, travel_notices.py:49-51
- §3.1 — revise — mismatch — operator block takes required `reason` field accepting any of the four block_reason values; block/unblock from wrong states → `ERR_INVALID_STATE` — routes/cards.py:93-122
- §3.2 — insert — ambiguity — `high_risk_multiplier` accepts any JSON number — routes/rule_sets.py:42-48
- §3.2 — revise — mismatch — `scope` included in tunable fields; merged-threshold validation; tuning non-DRAFT → `ERR_INVALID_STATE` — routes/rule_sets.py:20-24, 164-176
- §3.2 — insert — ambiguity — activate non-DRAFT / retire RETIRED → `ERR_INVALID_STATE` — routes/rule_sets.py:187-188, 210-211
- §3.3 — revise — ambiguity — blocked-card intake never consults ruleset resolution (no `ERR_NO_ACTIVE_RULESET`) — routes/auth_transactions.py:70-78
- §3.3 — revise — ambiguity — no qualifying amount tier (incl. empty tiers) contributes 0 — services/domain.py:536-542
- §3.3 — revise — mismatch — cross-border product truncated toward zero to integer (non-integer multiplier accepted) — services/domain.py:547-551
- §3.3 — revise — ambiguity — shadow rescore reads current card `fraud_flag`/ACTIVE notices vs original `scored_at`; blocked card at read time → `shadow_score` null, `shadow_decision` DECLINE, `shadow_ruleset_id` set — services/domain.py:725-751
- §3.4 — insert — ambiguity — alerts start with `resolution` null, `fraud_credit_cents` 0 — services/domain.py:632-647
- §3.4 — revise — mismatch — queue ordering applies only when filtered `alert_status=OPEN`; remaining ties by `id` ascending ("never by id" removed) — routes/fraud_alerts.py:162-166
- §3.5 — revise — ambiguity — 60-minute gap counts all account contacts of any channel/status incl. IN_APP; exactly 60 min allowed — routes/verification_contacts.py:41-50
- §3.5 — insert — ambiguity — completing a non-PENDING contact → `ERR_INVALID_STATE` — routes/verification_contacts.py:108-109
- §3.5 — revise — ambiguity — respond path: zero fraud credit, `assigned_to_user_id` stays null, already-resolved/EXPIRED → `ERR_INVALID_STATE` — routes/fraud_alerts.py:219-257
- §3.5 — revise — mismatch — reopen rejected at-or-after `resolved_at`+30d (impl `>=`); reopen retains assigned/resolution/credit/resolved_at; "passes `sla_expires_at`" → "reaches" — routes/fraud_alerts.py:270-285, services/domain.py:394-409
- §3.6 — revise — ambiguity — event auto-close also checked on event reads — routes/compromised_card_events.py:84
- §3.6 — insert — ambiguity — decide on non-PENDING (incl. auto-approved) → `ERR_INVALID_STATE` — routes/reissue_decisions.py:56-57
- §3.8 — insert — ambiguity — repeated id in `transaction_ids` contributes a provisional line per occurrence — routes/loss_entries.py:46-53, services/domain.py:665-673
- §3.8 — insert — ambiguity — book from non-ESTIMATED → `ERR_INVALID_STATE` — routes/loss_entries.py:103-104
- §3.8 — revise — mismatch — filing on wrong-state loss → `ERR_INVALID_STATE`; `claimed_cents` < 1 → `ERR_INVALID_REQUEST` (not `ERR_RECOVERY_EXCEEDS_OUTSTANDING`) — routes/recovery_filings.py:28-47
- §3.9 — insert — ambiguity — confirm/dismiss from wrong state → `ERR_INVALID_STATE` — routes/fraud_rings.py:112-113, 149-150
- §3.10 — revise — mismatch — overlap check sees notices as stored (no lazy expiry pass at creation; stale ACTIVE still blocks) — routes/travel_notices.py:53-62
- §3.10 — revise — ambiguity — cancelling non-ACTIVE notice → `ERR_INVALID_STATE`, expiry pass runs before cancel — routes/travel_notices.py:97-103
- §3.11 — insert — ambiguity — metrics readable for rulesets in any status — routes/rule_sets.py:217-224

Everything else in the PRD (endpoint/role table, error catalogue, scoring formula, cascade semantics, INV-CREDIT/INV-LOSS, rounding order, tier thresholds, SoD rules) was verified against the implementation line-by-line and already pinned uniquely — no changes needed.

## Step 7–9: Test / diagnose / iterate — 2026-08-15T09:05:00.000Z

Ran the 8-round parallel stability sweep (`prd-bench-local-run --isolation per-test-server`, 8 concurrent rounds).

**Iteration 1 baseline**: 105/113 passed in every round; the same 8 tests failed deterministically in all 8 rounds (no flakiness — pure deterministic defects):

1. `test_05::test_reissue_auto_approve_after_due_date`, `test_06::test_alert_created_in_open_with_initial_priority`, `test_08::test_confirm_flags_in_window_cards_and_spawns_decisions` — asserted exact timestamp strings (`2026-08-07T12:00:00Z`); implementation emits `...T12:00:00.000Z`.
2. `test_08::test_confirm_escalates_open_alerts_of_high_tier_accounts` — alert priority stayed 25, expected 225.
3. `test_11::test_full_payment_cascades_to_fully_recovered_and_low_tier` — account tier MEDIUM, expected LOW.
4. `test_11::test_loss_drops_out_at_91_days` — rolling loss stale at 5500 after clock advanced 91 days.
5. `test_12::test_two_qualifying_accounts_rejected`, `test_12::test_exactly_three_accounts_succeeds` — setup blew up with ERR_NO_ACTIVE_RULESET.

**Diagnoses and fixes** (no tests deleted — every failure traced to a fixable artifact):

- *Timestamp format (3 tests)* — PRD §2.4 scopes "three fractional digits" to `created_at`/`updated_at` (and §2.2 to `api_request_timestamp`); the string format of computed timestamps (`sla_expires_at`, `due_at`) is PRD-silent, only their *values* are pinned ("creation plus 72 hours", "confirmed_at plus 5 days"). STEP 1c partial-coverage: kept the covered arithmetic assertion, dropped the uncovered format assertion — the three tests now compare parsed instants via a new `parse_iso8601` helper in `test_helpers/assertions.py`.
- *Escalation (1 test)* — TEST BUG in `test_08` `_setup_cascade`: the fixture created manual alert m1 at 2026-08-01, then advanced the clock to 2026-08-10 (past m1's 72h SLA), tripping PRD §2.5 lazy expiry on clock advance; EXPIRED is terminal, so m1 could not be escalated. Moved m1 creation to after the clock returns to 2026-08-02T12:00 so it never expires; confirmed_at/due_at assertions unchanged.
- *Recovery cascade tier (1 test)* — FIXTURE BUG in `test_helpers/fixtures.py::setup_confirmed_fraud_txn`: a 200000-cent intake scores REVIEW under RS-STD, auto-creating a SCORING_REVIEW alert (PRD §3.3) that the fixture left dangling OPEN, forcing `risk_tier` MEDIUM per §3.1. The fixture now resolves that auto alert FRAUD as well (claim → contact with a +61-minute clock bump for the §3.5 per-account contact gap → resolve), leaving the account alert-quiet. APPROVE-scoring setups are untouched.
- *Rolling 90-day window (1 test)* — IMPLEMENTATION BUG: derived fields (`rolling_90d_loss_cents`, `risk_tier`) were only recomputed on writes, so a pure clock advance left them stale. PRD §2.11 defines the field as a sum over the window "ending at the current logical time". Fixed in `services/domain.py::apply_time_based_transitions` (recompute every account on clock advance) and `routes/accounts.py` (`get_account`/`list_accounts` recompute before filtering/serializing). Recompute touches the row only when a value actually changes (§2.4: derived-field recomputations count as mutations).
- *Ring setup (2 tests)* — TEST BUG in `test_12::TestRingDetectBelowMinimumAccounts._seed_accounts`: authorizations were posted before any ACTIVE ruleset existed (PRD §3.3: intake then fails ERR_NO_ACTIVE_RULESET). Moved `create_active_ruleset()` ahead of the first intake, matching the sibling class's correct ordering.

**Iteration 1 re-sweep**: all 8 rounds 113/113 passed. Exit.

(One environment note: the first post-fix sweep was killed by a host-level timeout while other pipelines saturated the box; the sweep was relaunched detached via setsid with a completion marker and completed cleanly.)
