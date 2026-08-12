# Worklog — task_0933_data_broker_removal_personal_cyber

Scenario (verbatim): `933. Data-Broker Removal & Personal Cyber Service: scan & exposure inventory, opt-out/removal request per broker, recurring re-scan & re-removal, breach-monitoring & alert, password/identity hygiene, family plan, VPN/device add-on, reporting`

Difficulty target: **beyond-Expert** (user asked "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-08T17:13:00.000Z

Created `tasks/task_0933_data_broker_removal_personal_cyber/workspace`. Next index after task_0932.

## Step 3: Copy shared files — 2026-08-08T17:13:10.000Z

Copied `INSTRUCTION.md` → `workspace/INSTRUCTION.md` (done early alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-08T18:15:00.000Z

All three artifacts written; both `yaml.safe_load` and `scaffold_lint.py` clean.

```
SCAFFOLD §1.8/§1.9 -> §1.5 lint report
  §1.5 endpoints declared:    81
  §1.1 entities declared:     17
  §1.8 instances scanned:     20
  §1.9 instances scanned:     83
  Calls scanned (§1.8+§1.9):  820
VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

Files: SCAFFOLD.yaml (3887 lines), SCAFFOLD_DIFFICULTY_DESIGN.yaml (1883), SCAFFOLD_CORNER_DESIGN.yaml (4005).

### (e) Final counts
| Dimension | Count |
|---|---|
| Entities | 17 |
| Endpoints | 81 (incl. 1 `/_clock` test-driving endpoint) |
| State machines | 15 across 13 entities; **12 non-linear** (3 linear: Member.status, BreachAlert.status, BillingCycle.status) |
| Calculations | 26, of which **6 dual-variant** |
| Error codes | 61 (every one triggered by a design instance) |
| Validation ladder rungs | 47 (rungs 13–15 are the global write gates) |
| OCC rules | 4 |
| Conservation invariants | 4 (entitlement units, seat-pool capacity, exposure row count, alert row count) |
| Max cascade depth | **5** (Account ACTIVE→SUSPENDED → profiles PAUSED → queued scans CANCELLED → SCAN RELEASE ledger row → Account.scan_units_remaining) |
| §1.8 instances | 20 (9 rules × ≥2; 3 each for cross_entity_state_dependency and compensating_invariant) |
| §1.9 instances | 93 across all 9 guide sections (83 with recipes, 10 `excluded_because` stubs) |

Combinatorial modes: (a) `removal_sla_deadline` nested max over method buffer + jurisdiction floor; (b) `plan_proration_amount` round-then-multiply vs multiply-then-round (660 vs 667 on identical inputs); (c) `cycle_total_charge` loyalty tier keyed on the pre-discount total (1520 → discount 30 → total 1490, back below the 1500 threshold).

### (c) Constants
**65 declared constants, 0 undeclared.** ALL_CAPS grep surfaced 67 constant-shaped tokens; the 2 non-matches are the English words `CAPACITY`/`CAPPED` and the band enum member `MODERATE`.

### (d) Reachability self-repairs (8)
1. **`ERR_PROFILE_NOT_ACTIVE` on `POST /scan-runs/{id}/start` was unreachable** — pause/retire cancels every QUEUED scan, so rung 18 always pre-empts it. Narrowed rung 20 to `POST /scan-runs` + `/retry` (FAILED scans survive a pause).
2. **`ERR_AUTHORIZATION_REVOKED` on the DRAFTED→SUBMITTED edge was unreachable** — revocation voids all DRAFTED requests and rung 16 blocks drafting new ones. Reachable path is ESCALATED→SUBMITTED; §1.9 instance repointed.
3. **`ERR_CYCLE_CLOSED` was unreachable** — close always mints a successor for an ACTIVE account; re-closing hits `ERR_ALREADY_TERMINAL` higher. Reworded rung 24 to "the account has no OPEN cycle"; reachable via suspend → close → resume.
4. **OCC rule 1 failed §1.2.1's serial-observability filter** — replaced with `identifier-add-stale-profile` (parent MonitoredProfile).
5. **`Plan.tier` uniqueness made corner states unreachable** — removed the uniqueness clause.
6. **Arithmetic feasibility** — retuned fixtures so every declared divergence has a witness: add-on 305×1×21/30 = 213.5 (ceil 214 vs floor 213); plan delta 1000 over 20 days (660 vs 667); loyalty pre-discount 1520 → 1490.
7. **6 `FK_REVERSE_UNREACHABLE` violations** — renamed every path parameter to `{id}`.
8. **Broker counter definitions drifted** (ever-entered vs CURRENT status) — harmonised to CURRENT status.

YAML-lint fixes: quoted `field?` tokens in flow input sequences, quoted `$.data[0].x` capture paths, converted flow-style `grounds:` lists to block style.

### Domain seams — realization
1. **Parallel exposure/removal axes** — `ExposureRecord.status` (FOUND→SUPPRESSED→REAPPEARED→RE_SUPPRESSED, unbounded loop) and `RemovalRequest.status` (DRAFTED→SUBMITTED→ACKNOWLEDGED→{COMPLETED|REJECTED|EXPIRED}→ESCALATED→SUBMITTED, capped at 2) advance independently; `suppression_count`/`first_found_at`/`discovered_by_scan_id` survive every reappearance.
2. **Cadence × statutory windows** — `removal_sla_deadline` = `max(broker.response_window_days + METHOD_SLA_BUFFER_DAYS[method], JURISDICTION_SLA_FLOOR_DAYS[jurisdiction])`; expiry inclusive on `current_utc >= sla_deadline_at`.
3. **Re-removal suppression window** — `reappearance_classification`, `REAPPEARANCE_COOLOFF_DAYS 45`, strict: 44 days mutates the existing row (fee-exempt), 45 creates a fresh row consuming entitlement.
4. **Family-plan entitlement** — `EntitlementLedgerEntry` (PROFILE/SCAN/REMOVAL × GRANT/CONSUME/RELEASE), `granted − consumed + released == remaining`, per-member sub-cap checked strictly *after* the shared pool.
5. **Breach dedup + monotone severity** — dedup keys on (breach_event_id, identifier_id); RE_INGEST_MONOTONE only ever raises the band.
6. **Hygiene score dual-variant** — weighted over OPEN `CredentialFinding` rows, capped at 70 *before* the 0.60 two-factor multiplier, banded at 80/60/40 with a fixture landing exactly on 60.00.
7. **Add-on seats** — `seat_pool_occupancy` (half-open, zero adjacency buffer), `SEAT_REBIND_COOLOFF_HOURS 72` on voluntary release; suspension VOIDs seats but preserves `bind_count`, resume restores with no cool-off.
8. **Billing/proration fork** — UPGRADE rounds the daily rate then multiplies; DOWNGRADE multiplies then rounds once; add-ons prorate on the *inclusive* remaining-day count, ceil on charges / floor on credits.
9. **Verification-of-identity gate** — brokers with `requires_identity_verification` need a VERIFIED `IdentityDocument`; expiry strict at `expires_at`, blocks submission (rung 26), never rolls an ACKNOWLEDGED request back.
10. **Global write gates** — rungs 13/14/15 (`LEGAL_HOLD`, `CANCELLED`, `SUSPENDED`) above every per-endpoint state gate; only `POST /accounts/{id}/legal-hold` exempt.
11. **Reporting** — three derived-never-stored endpoints (per-broker compliance with LIFETIME/CURRENT_WINDOW scopes and `created_at ASC` tie-breaks; per-member exposure summary with pinned 0.0000 zero-denominator ratio; cycle entitlement statement with `consumed DESC, created_at ASC` breakdown).
12. **Authorization revocation** — `Member.GRANTED→REVOKED` voids only DRAFTED requests and refunds their units (depth-4 cascade); SUBMITTED/ACKNOWLEDGED/ESCALATED continue untouched.

## Step 4: Generate PRD — 2026-08-08T18:35:00.000Z

PRD at `workspace/PRD.md` — **526 lines, 14,688 words.** §1 Introduction (3 paras) · §2 with 11 subsections (2.2 byte-verbatim from `section-2.2-response-structure.md`) · §3 with 9 domain subsections · §4 endpoint table · §5 error table.

### Zero-Silence audit (mechanical, run against the generated file)
| Category | Required | Present | Missing |
|---|---|---|---|
| `entities[].fields[].name` (backticked) | 144 | 144 | **0** |
| `endpoints[].input` + output identifiers | 103 | 103 | **0** |
| `endpoints[].query_params` (`?`-suffixed) | 25 | 25 | **0** |
| path params (`{id}`) | 1 | 1 | **0** |
| `errors[]` in §2/§3 **narrative** (not just §5 table) | 61 | 61 | **0** |
| `endpoints[]` in §4 table | 81 | 81 | **0** |
| SM transitions with explicit `FROM → TO` in prose | 57 | 57 | **0** |
| `calculations[]` fully expressed (all 6 dual-variant forks on both branches) | 26 | 26 | **0** |
| declared constants with numeric value in business context | 65 | 65 | **0** |
| §3 path-purity: 935 backtick tokens → 0 starting `/`, 0 bare HTTP methods, 0 method+path | — | — | **PASS** |
| fuzzy words / pseudocode operators (`>=`, `==`, `&&`, "approximately") | 0 | 0 | **PASS** |

Hard parts preserved verbatim: strict-vs-inclusive boundaries throughout (45-day reappearance cool-off strict, 7-day rescan inclusive, 72h rebind inclusive, 24h reopen buffer inclusive-on-allow, `expires_at` strict, SLA expiry inclusive, `on_time` inclusive, identifier cap strict, invite cap strict vs downgrade cap inclusive); proration rounding fork (upgrade rounds daily rate then multiplies; downgrade multiplies then rounds once); add-on ceil-charge/floor-credit on the inclusive remaining-day count vs the plan's exclusive count; pre-discount-keyed loyalty tier; cap-before-multiplier / round-after hygiene score; full 47-rung ordering with each rung's `applies_to` scope and error code, incl. rung 8's closed iff-list ("no other field routes to `ERR_INVALID_ENUM`").

### Un-adjudicated friction points (rendered neutrally, NOT resolved) — 8
1. **Rung 18 vs rung 19.** A: lowest-number-wins is absolute → terminal rows report `ERR_INVALID_STATE` and `ERR_ALREADY_TERMINAL` is unreachable. B: terminal rows report `ERR_ALREADY_TERMINAL`, so rung 19 is consulted first. (§2.6 closing para.)
2. **Rung 32 (reopen buffer) vs rung 35 (duplicate request).** A: ladder governs, buffer before duplicate. B: `exposure_channel_occupancy` as written tests the open-request condition first. (§2.6 / §3.5.)
3. **Lazy `VERIFIED → EXPIRED` vs rungs 25/26.** A: transition fires on consult → rung 25 `ERR_IDENTITY_VERIFICATION_REQUIRED`. B: rungs read stored status → rung 26 `ERR_IDENTITY_DOCUMENT_EXPIRED`. (§3.5.)
4. **Submit precondition "exposure status in `{FOUND, REAPPEARED}`" has no declared error code.** A: routes to a generic state rejection. B: unreachable invariant like the sibling authorization precondition. (§3.5, no code invented.)
5. **BreachAlert severity: declared edge list vs general monotonicity rule.** A: unenumerated jumps (`MEDIUM → CRITICAL`) admitted by the general rule. B: only enumerated edges fire. (§3.6.)
6. **`plan_proration_amount` variant selection when `change_kind` contradicts the fee direction.** A: no variant applies, nothing booked. B: `change_kind` alone selects. (§3.9.)
7. **"Exactly one `PRIMARY` per Account"** declared but no rung/error enforces it. A: some existing code rejects a second. B: descriptive only, invitations unguarded. (§3.1.)
8. **`CredentialFinding.weight` on a `REMEDIATED` row.** A: `weight` always reads the finding-type penalty, only its *contribution* is `OPEN`-gated. B: `weight` reads 0 once remediated. (§3.7.)

### §2-summary vs §3-detail cross-check — performed
Re-read every §2 overview against its §3 hop-by-hop rendering; agreement confirmed on the depth-5 suspend cascade (§2.11 vs §3.2 hops 1–5 + add-on branch), the depth-4 revoke cascade, the removal-completion cascade (§2.11 vs §3.5 hops 1–3), the 47-rung `applies_to` scopes vs their §3 guards (rung 16's four ops, rung 20's two-op scope with `start` excluded, rungs 21/22's four each, rung 45/46's fee-exempt skip and pool-before-subcap order), the 4 OCC rules vs their §3 homes, the 3 rounding asymmetries (§2.9 vs §3.8/§3.9), the 4 conservation invariants (§2.10 vs §3.4/§3.6/§3.8/§3.9), and the §2.11 no-op rule vs the §3.6 re-ingest rule. **No drift found**; the only §2/§3 tensions are friction points 1 and 2, carried forward deliberately and flagged in both places.

Constraint honoured: neither design yaml was opened, grepped or referenced.

## Step 5: Generate unit tests — 2026-08-08T19:10:00.000Z

| | |
|---|---|
| §1.8 (Difficulty) instances translated | **20 / 20**, 0 skipped — 42 tests, every instance ≥ 2 |
| §1.9 (Corner) non-stub instances translated | **83 / 83**, 0 skipped — 83 tests, every instance ≥ 1 |
| `excluded_because:` stubs | 10, all cross-references resolve; none translated |
| Total `def test_` | **125** |
| `Design:` tag count | **125** (one per test; 0 unresolved, 0 dual-tagged) |
| `skip`/`skipif`/`xfail` | **0** |
| PRD citations checked verbatim | **209 / 209** pass a whitespace-normalised literal grep |

Output: `test_helpers/` (9 files, 2128 lines), `test_suite/` (conftest + 19 files, 4170 lines).

### Per-instance skips — none. Three sub-assertions dropped/widened as non-derivable:
1. **`Corner/state_machines/member_activation_requires_the_issued_invitation_token`** — the wrong-token leg asserts `ERR_VALIDATION`; PRD names no error for token *mismatch* (rung 6 = absence, rung 7 = type). Dropped that leg; kept the success leg (`INVITED → ACTIVE`, token cleared, `activated_at` stamped). **PRD defect.**
2. **`Corner/state_machines/credential_finding_remediate_then_reopen_rescoring_cycle`** — friction 8; `weight == 25` asserted only on the two `OPEN` observations.
3. **`Corner/calculations/entitlement_statement_member_breakdown_ordering_and_tiebreak`** — §3.9 pins the ordering but never names the row keys; tolerant key lookup keeps the ordering assertion fair.

### Friction handling
Frictions **2, 5, 6, 7 avoided by construction** — no fixture reaches the ambiguous configuration: rung 32/35 legs are run one-at-a-time (duplicate leg has an open request and no closed one; buffer leg the reverse); the only escalation exercised is the declared `HIGH → CRITICAL`; every plan change pairs `UPGRADE` with a fee rise and `DOWNGRADE` with a fee fall.

Frictions **1** and **3** use `validate_error_is_one_of`, flagged in the docstring: `cancel_account_twice…` and `identity_document_reject_branch…` accept `{ERR_ALREADY_TERMINAL, ERR_INVALID_STATE}` (HTTP 409 either way); `test_removal_submit_with_a_verified_document_past_its_expiry_is_refused` accepts `{ERR_IDENTITY_DOCUMENT_EXPIRED, ERR_IDENTITY_VERIFICATION_REQUIRED}`.

**Friction 3 also contaminated a success leg** the design index did not anticipate: the recipe verifies a doc expiring `2026-05-10`, moves the clock *to* `2026-05-10` (firing the lazy transition under one reading), then back to `2026-05-09` and expects a successful submit — under "lazy transition applied" the doc is permanently `EXPIRED`. Split into a separate fixture whose clock never reaches `expires_at`.

Friction **4** is asserted nowhere.

### Agreement-by-construction re-derivations
- **Friction 3, success leg.** `expires_at = 2026-05-10T00:00:00Z`, verify at `2026-05-01`, submit at `2026-05-09`. Reading A (lazy transition first): trigger `current_utc >= expires_at`; `05-09 < 05-10` → does not fire, status `VERIFIED`, rungs 25/26 pass. Reading B (rungs first): rung 25 sees `VERIFIED` → pass; rung 26 requires reaching `expires_at` → pass. Both: HTTP 200, `effective_window_days = max(20 + 2, 30) = 30`, `sla_deadline_at = 2026-06-08T00:00:00Z`. Identical.
- **Friction 8, `weight`.** Both readings agree an `OPEN` row carries the type penalty; only `REMEDIATED` diverges (25 vs 0). All three `weight == 25` assertions read an `OPEN` row.
- **Frictions 1 and 3, error legs.** Non-numeric — `validate_error_is_one_of` over the two faithful codes plus a shared HTTP 409; every state assertion identical under both.

### PRD defects noticed
1. No error code for an invitation-token mismatch (§3.1 states the rule; the ladder names no code).
2. `BreachEvent.ingest_count` / `alert_count` are unreadable — no `GET /breach-events` in §4. Substituted observable equivalents (`GET /breach-alerts?breach_event_id=…` `total_count`, per-ingest created/escalated/unchanged split).
3. `Broker` has no single-row read either — all broker-score assertions go through `GET /brokers/{id}/compliance-report`.
4. Rung 26's wording ("every `VERIFIED` document … has reached or passed `expires_at`") contradicts §3.5's refusal to order the lazy transition against rungs 25/26, making rung 26 unreachable under one permitted reading.

## Step 6: Generate implementation — 2026-08-08T19:12:00.000Z

31 Python modules / 4,832 lines in ~25 bounded writes. 15 top-level modules + 15 route blueprints + `start.sh` + `requirements.txt`. In-memory only; store empty every boot.

**(B) Route diff gate — MISSING = 0, EXTRA = 0, 81 endpoints.** Scaffold `endpoints[]` enumerated programmatically, app booted in-process, `app.url_map` dumped, params normalized, sets diffed. Exact match.

**(C) EADDRINUSE hardening — 12 rounds, 0 start failures.** `app.py` pre-binds with `SO_REUSEADDR` in a 40 × 0.25 s retry loop, serves via `make_server(..., fd=sock.fileno())`. Tight `kill -9` + relaunch loop: `ROUNDS=12 START_FAILURES=0`.

**(D1) Timestamps.** One producer, `clock.render_instant()`. Rule: server-stamped instants (and derivations) render `YYYY-MM-DDTHH:MM:SS.mmmZ`; caller-supplied instants stored as input fields echo byte-for-byte; the clock endpoint echoes literals both ways. Rows carry both `expires_at`/`expires_at_dt` (and `breach_date`/`breach_date_dt`) so logic never touches the literal. HTTP-verified: `created_at` = `2026-05-01T00:00:00.000Z`; clock at `...T12:34:56.789Z` → derived `ends_at` = `2026-05-31T12:34:56.789Z`; `expires_at` sent as `2026-12-31T00:00:00+00:00` echoes exactly; `previous_utc` = `2026-05-01T00:00:00Z`. No wall-clock read anywhere (grep-verified).

**(D2) Enum routing — closed iff-list.** Route to `ERR_INVALID_ENUM`: `tier`, `role_in_family`, `opt_out_method`, `jurisdiction`, `document_type`, scan `kind` (body), `exposure_kind`, `finding_type` (body), `identifier_type` (body), `addon_type`, each `record_types` element, `change_kind`, `hold_state`, `action`, `scope`, and the `status`/`severity`/`resource_type`/`entry_type` list filters. **No other field routes here.** Deliberate exclusions: the `kind`/`finding_type`/`identifier_type` *query filters* (filter, never 422). HTTP-verified both sides: 15 fields → `ERR_INVALID_ENUM`; wrong-typed → `ERR_VALIDATION`; out-of-range → `ERR_VALUE_OUT_OF_RANGE`; missing → `ERR_VALIDATION`; excluded filters → 200.

**(E) The eight friction adjudications** — rule: keep the most PRD-declared behaviour reachable; `# Adjudication of friction N` comment at each site.
1. **Rung 18 vs 19** (`states.py`) — **terminal test first**. Literal lowest-number-wins makes `ERR_ALREADY_TERMINAL` unreachable everywhere (a terminal state declares no outgoing edge). No §1.2 transition originates from a terminal state, so 19-before-18 loses nothing. Verified: COMPLETED request → `ERR_ALREADY_TERMINAL`; RUNNING scan re-started → `ERR_INVALID_STATE`.
2. **Rung 32 vs 35** (`removals.py`) — **buffer before duplicate**. Both codes stay reachable either way, so reachability doesn't separate them; tie broken by §2.6's unconditional lowest-numbered-rung rule. Verified incl. the doubly-violating case (clock rewind) → rung 32 wins.
3. **Lazy `VERIFIED→EXPIRED` vs rungs 25/26** (`removals.py`) — **rungs evaluated against the stored status, transition applied afterwards**. Applying it first leaves no `VERIFIED` doc, making `ERR_IDENTITY_DOCUMENT_EXPIRED` unreachable for every input. Verified: expired VERIFIED doc → `ERR_IDENTITY_DOCUMENT_EXPIRED`, doc then reads `EXPIRED` with `version` bumped; the next attempt falls to rung 25.
4. **Submit precondition with no code** (`removals.py`) — **enforced, reported as `ERR_INVALID_STATE`** (no code invented), in the scaffold's declared precondition order (after rung 22, before 25). Reachable (draft against an already-SUPPRESSED exposure past the 24-h buffer). Not enforcing it strands completion hop 2.
5. **Severity edge list vs monotonicity** (`breaches.py`) — **the general strictly-greater-ordinal rule governs; `MEDIUM→CRITICAL` and `LOW→CRITICAL` admitted.** Restricting to the enumerated list would contradict two stated invariants (`severity_points` = highest ever computed; escalate-never-de-escalate). Verified, incl. within-band growth being a true no-op (version untouched).
6. **`plan_proration_amount` with a contradictory `change_kind`** (`accounts.py`) — **no variant fires, both figures 0, the change still succeeds** (repoints `plan_id`, bumps version). Rejecting or inventing a third variant would delete declared behaviour. Verified.
7. **"Exactly one PRIMARY per Account"** (`accounts.py`) — **not enforced.** Enforcing needs a code the catalogue lacks and would make the declared `role_in_family: PRIMARY` invitation path unreachable. `is_primary` stays false → rung-4 identity resolution unaffected. Verified: second PRIMARY → 201, `is_primary: false`.
8. **`CredentialFinding.weight` when REMEDIATED** (`serializers.py`) — **always the per-type penalty**; §3.7 gates the *contribution*, not the weight. Verified: weight 18 in both states while `raw_penalty` drops to 0.

**(F) Determinism.** Ids are valid UUID strings whose leading 48 bits carry a monotonic counter (version nibble `4`, variant `8`, random tail). All lists sort `(created_at, id)`. Verified: five identifiers minted at one frozen instant list back in creation order.

**Verification totals.** Four HTTP suites, ~330 assertions, all green: envelope/pagination/RBAC/ladder ordering; all 15 404 families; all 61 error codes wired; hygiene cap-before-multiplier (raw 100 → capped 70 → 2FA 42.0 → 58.0/WEAK); upgrade 660 vs downgrade 667 on the same delta/span; add-on ceil-charge vs floor-credit; loyalty tier from the pre-discount total; SLA `max(window+buffer, floor)` = 97 for POSTAL/US_CA and flat 15 on resubmission; 44→REAPPEARANCE / 45→FRESH; 24-h buffer inclusive at exactly +24 h; 72-h rebind inclusive; strict identifier (8th ok, 9th rejected) and member caps; depth-5 suspend cascade, depth-4 revoke cascade, cancel cascade, member-removal cascade; `ERR_CYCLE_CLOSED` via close-while-suspended then resume; pool error winning over sub-cap.

**PRD gaps worked around (beyond the 8 frictions).**
- Preconditions with no declared code: invitation-token mismatch → `ERR_VALIDATION`; removing the primary member and verifying a document at/past `expires_at` → `ERR_INVALID_STATE`.
- **No Broker state machine** declared although the entity has `ACTIVE`/`RETIRED`; re-retiring → `ERR_INVALID_STATE` with no terminal set.
- **`SEAT_RELEASED` credit** is keyed on the `ACTIVE → SUSPENDED` transition by the calculation trigger and §3.8 but omitted from §3.2's narrative; booked on both the endpoint and the cascade.
- **`findings_count`/`reappearance_hit_count`** are `source: computed` and `POST /scan-runs/{id}/findings` is the only transition endpoint whose side-effect list omits a version bump → the scan row's `version`/`updated_at` are untouched there (`BreachEvent.ingest_count` is `source: system`, so ingest *does* bump).
- **Rung 43 (profile quota)** written as "profile activation" generally, but §3.3 says `PAUSED → ACTIVE` "requires only" three things and consumes nothing; applied to the `DRAFT` edge only, else an exhausted pool permanently freezes un-pausing.
- **`primary_member_email`** not subjected to the `@` rule (§3.1 states it only for invitations).
- **Multi-FK body resolution order** undeclared; `POST /device-seats` resolves in the endpoint's declared input order (`addon_id`, then `member_id`).

### Orchestrator isolation check
Step 5 finished ~2.8 min before Step 6, so `test_suite/` existed on disk during Step 6's tail. Containment verified mechanically: `grep -rn "test_suite\|test_helpers\|conftest" workspace/implementation/` → **0 hits**. Also confirmed: 125 `def test_` == 125 `Design:` tags, 0 skip/xfail markers, and 0 persistence/wall-clock hits in `implementation/` (the two grep matches are a docstring in `store.py` and a test function *named* `…without_skipping`).

## Step 7: Run tests and iterate — 2026-08-08T19:35:00.000Z

**Result: clean 8-round sweep — 125/125 in all 8 rounds, 0 implementation changes.**

### Iterations
1 baseline round (123/125) → 1 fix iteration (2 test-suite fixes) → 1 verification round (125/125) → full 8-round sweep (8×125/125).

### Tests deleted
**None.** Both failures were test bugs with exact PRD coverage, fixed under STEP 2 rather than deleted.

### Fixes to `test_helpers/` — none. Fixes to `implementation/` — none (the impl was the PRD-faithful side in both cases).

### Fixes to `test_suite/`
1. **`test_09_write_gates_and_ladder.py::test_cancelling_an_already_cancelled_account_runs_no_second_cascade`** — asserted `validate_error_is_one_of([ERR_ALREADY_TERMINAL, ERR_INVALID_STATE])`; server returned `ERR_ACCOUNT_CANCELLED`. PRD rung 14 ("the account in scope has a status other than `CANCELLED` … Applies to every account-scoped mutating endpoint except the legal-hold capability itself") pre-empts rungs 18/19, and §2.6 states the write gates "deliberately sit above every per-endpoint state gate." Rung 15 lists account cancellation among its exceptions; **rung 14 does not** — that asymmetry is decisive. Tightened to an exact `validate_error(…, ERR_ACCOUNT_CANCELLED, 409)` — a strengthening that also removes the test's dependence on friction 1.
2. **`test_05_removal_lifecycle.py::test_the_shared_pool_error_is_reported_while_the_subcap_has_room`** — fixture built `removal_quota_per_cycle=1, per_member_removal_subcap=5`, which PRD rung 9 forbids ("`per_member_removal_subcap` is at least 1 and at most `removal_quota_per_cycle`"); correctly rejected `ERR_VALUE_OUT_OF_RANGE` at setup. Rebuilt with a legal plan (`quota=2, subcap=2`), draining the pool with **two** members instead of raising the sub-cap; the drafting member still holds 1 of 2 sub-cap units when rung 45 fires.

### (i) Clean-sweep verification
| Check | Result |
|---|---|
| 8 `results.N.json` present, parseable, 125 rows each | PASS |
| `passed=125 failed=0 errors=0`, status set `{'passed'}` | PASS (all 8) |
| Sorted test-name lists byte-identical across rounds | PASS — SHA `ee88f029…` on all 8 |
| `def test_` == collected == `Design:` tags | PASS — 125 / 125 / 125 (125 unique names) |
| skip/xfail/skipif markers | 0 (2 grep hits are a test *name* `…without_skipping` and the word "skipped" in a docstring) |
| Persistence / wall-clock grep over `implementation/` | 0 functional hits (only a `store.py` docstring disclaiming them) |
| Route diff: scaffold `endpoints[]` vs live `app.url_map` | **81/81, 0 missing, 0 extra** |
| `Killed` per round log | exactly 1 each (expected pre-boot swap); **0 tracebacks** |
| `find … -newer results.1.json` | empty |
| `grep test_suite\|test_helpers\|conftest` in `implementation/` | 0 hits (isolation intact) |

Orphan hygiene: reaped 5 leaked `ppid=1` Flask servers (from a co-tenant task_0935 pipeline) before the sweep.

*Orchestrator re-verified independently:* all 8 rounds `passed=125 failed=0 rows=125 statuses={'passed'}`, single name-set signature `ee88f02943ec` across all 8, `find -newer results.1.json` empty.

### (ii) Friction cross-check — per-friction verdicts (no DEPENDS)
1. **Rung 18 vs 19 — AGREEMENT-BY-CONSTRUCTION.** Only `test_a_rejected_document_stays_invalid_and_cannot_then_be_verified` touches it (verify a `REJECTED` doc: rung 18 has no edge, rung 19 sees terminal — both fail). Accepts either code; both map to 409. The Step-7 fix removed the second toucher.
2. **Rung 32 vs 35 — AGREEMENT-BY-CONSTRUCTION.** Legs run one at a time. Duplicate leg: incumbent `DRAFTED`, no `closed_at` → rung 32 ineligible. Buffer leg: incumbent `VOIDED` → outside `{DRAFTED,SUBMITTED,ACKNOWLEDGED,ESCALATED}` → rung 35 ineligible. Re-derived: 0 s < 86400 blocked; 86399 < 86400 blocked; exactly 86400 admitted; account 60 − 2 + 1 = 59. test_13 lap 2 drafts 44 days after a `COMPLETED` incumbent — neither rung eligible.
3. **Lazy `VERIFIED→EXPIRED` vs rungs 25/26 — AGREEMENT-BY-CONSTRUCTION.** Error leg: `expires_at = 2026-05-10T00:00:00Z`, clock exactly `2026-05-10T00:00:00Z`. Reading A → doc `EXPIRED` → rung 25 → `ERR_IDENTITY_VERIFICATION_REQUIRED` (403). Reading B → stored `VERIFIED` passes 25; rung 26 `05-10 ≥ 05-10` → `ERR_IDENTITY_DOCUMENT_EXPIRED` (409). The test accepts both and asserts no HTTP status, so the 403/409 split is absorbed; request stays `DRAFTED` under both. Success leg: clock `05-09 < 05-10` → trigger false under both; `max(20+2, 30) = 30`; `05-09 + 30×86400 s = 2026-06-08T00:00:00Z`.
4. **Submit precondition with no declared code — CLEAN.** No test submits with the exposure outside `{FOUND, REAPPEARED}`; test_13's lap-2 suppression starts from `REAPPEARED`. Structurally near-unreachable: needs two live requests on one exposure, which rung 35 forbids.
5. **BreachAlert severity — AGREEMENT-BY-CONSTRUCTION.** Sole escalation: `15 + max(10, 30) + 5 + 0 = 50` → HIGH (ordinal 3); after one OPEN `BREACHED_PASSWORD`, `50 + 10 = 60` → CRITICAL (4). `HIGH → CRITICAL` is both an explicitly declared edge and satisfies `4 > 3`. Third ingest recomputes 50 (3 ≤ 4) → untouched under both. The unadjudicated `MEDIUM → CRITICAL` jump is never reached.
6. **Contradictory `change_kind` — CLEAN.** Every plan change pairs kind with fee direction (1200→2200 UP, 2200→1200 DOWN, 2200→3400 UP); fee ladder 1200 < 2200 < 3400 has no ties. Re-derived: UPGRADE `round_half_up(1000/30)=33 × 20 = 660`; DOWNGRADE `round_half_up(1000×20/30)=round_half_up(666.67)=667`.
7. **Exactly one PRIMARY — CLEAN.** No test invites `role_in_family: PRIMARY`; the one test passing `is_primary: true` in a body uses role `MINOR`, so both readings admit it with `is_primary` false.
8. **`weight` on a REMEDIATED row — AGREEMENT-BY-CONSTRUCTION.** Both `weight == 25` reads sit on `OPEN` rows; the `REMEDIATED` response is asserted only on `status`/`remediated_at`. Score assertions are friction-independent (§3.7 sums over `OPEN` only): 1 open → `100 − min(25,70)×1.00 = 75.00` MODERATE; 0 open → `100.00` STRONG.

### (iii) Near-miss register — tests fair only by accident
1. **`test_a_rejected_document_stays_invalid…`** — fair only because `ERR_ALREADY_TERMINAL` and `ERR_INVALID_STATE` share HTTP 409; its `status_code == 409` line would split the readings if either code's status differed.
2. **`test_removal_submit_with_a_verified_document_past_its_expiry_is_refused`** — the two admissible codes have *different* statuses (403 vs 409). Fair only because the test omits a status assertion; adding one — the habit everywhere else in this suite — makes it DEPENDS. **The most fragile test in the suite.**
3. **`test_removal_submit_succeeds_while_the_document_is_still_valid`** — one day of margin; clock 05-09 → 05-10 fires the lazy transition under reading A and turns 200 into 403.
4. **`test_the_reopen_buffer_admits_a_successor_at_exactly_twenty_four_hours`** — fair only because the incumbent is `VOIDED`; leaving it `ESCALATED` makes rungs 32 and 35 both eligible.
5. **`test_a_second_draft_on_an_occupied_exposure_is_refused`** — the mirror: fair only because the incumbent has no `closed_at`.
6. **`test_alert_severity_ratchets_upward…`** — first ingest lands at 50, only 5 above the HIGH floor of 45; `base_severity_points` 15 → 9 drops it to 44 (MEDIUM) and a heavier second ingest then produces the unadjudicated `MEDIUM → CRITICAL`.
7. **`test_alert_triage_runs_new_to_acknowledged_to_resolved…`** — 25 points sits *exactly* on the MEDIUM floor; friction-free only because it never escalates.
8. **`test_invited_member_ignores_server_owned_fields_from_the_body`** — fair only because `role_in_family` is `MINOR`; that literal changed to `PRIMARY` turns it into a direct friction-7 probe.
9. **`test_a_finding_cycles_open_remediated_open…`** — fair only because both weight reads are on OPEN rows; one added `assert remediated["weight"] == …` makes it DEPENDS on friction 8.
10. **The proration pair (test_12) and concurrent plan changes (test_11)** — fair only because no two plans in play share a fee; a same-fee plan reaches friction 6's "no variant fires" branch.
11. **`test_the_shared_pool_error_is_reported_while_the_subcap_has_room`** (the Step-7 rewrite) — discriminating only because the sibling draws the second unit; drop that leg and the owner breaches pool and sub-cap simultaneously, resting the test on §3.5's tie-break instead of isolating rung 45.
12. **`test_a_re_finding_at_forty_four/forty_five_elapsed_days…`** — not friction-related, but one-day margins on a strict branch boundary.

## Step 8: Finalize PRD — 2026-08-08T19:45:00.000Z

**Result: ZERO PRD edits — `PRD_FINALIZED.md` is byte-identical to `PRD.md`** (525 / 525 lines, 0.0% delta, md5 `ceb2e4ff98fcaadb2f234e9ff420a906` on both). Both `<step_7_diff>` items are test-fixture/test-assertion bugs against behavior the PRD already determines uniquely; in both, the implementation is the PRD-faithful side. (A legitimate zero, as on task_0923 — Step 8's skip condition wasn't met because two `test_suite/` fixes exist, but neither reveals a silence or mismatch.)

### Item 1 — `test_09::test_cancelling_an_already_cancelled_account_runs_no_second_cascade`
- (a) Subject: which rung reports a mutating call against a `CANCELLED` account — global write gate 2 (rung 14) vs the per-endpoint state gates (rungs 18/19) on the cancel endpoint.
- (b) Impl paths enumerated: `context.py:152-160` (`Ctx.write_gates()`, single choke point ordered legal_hold → CANCELLED → SUSPENDED); `routes/accounts.py:135,146,158,208,302,378` (every `write_gates` callsite — `resume`/`cancel` pass `skip_suspended=True`, **no** callsite skips the CANCELLED gate; `legal_hold` at `:164-184` is the only account-scoped mutator that never calls it); `routes/accounts.py:152-161` (cancel order: `ctx.path` → `ctx.own` → `write_gates` → `states.gate(("ACTIVE","SUSPENDED"))` → `cascades.cancel_account`, so "no second cascade" follows from rung 14, not 18/19); `states.py:3-16,44-49` (friction-1 adjudication, confirmed unreachable here); `errors.py:38,44,45` (`ERR_ACCOUNT_CANCELLED` = 409, matching rung 14).
- PRD coverage exact and already unique: rung 14 (§2.6 L113) applies to "every account-scoped mutating endpoint except the legal-hold capability itself"; rung 15 (L114) names account cancellation in its exemption list while rung 14 does not; §2.6 preamble (L98) and §2.7 (L154-156) both state the write gates sit above every per-endpoint state gate, and §2.7 enumerates cancellation as account-scoped. §2.6's deferred friction (L148) concerns only rungs 18 vs 19, which never run here.
- (c) No wording adjustment; any restatement would duplicate L113/114/154-156 and risk narrowing the gate's universal scope across six callsites.

### Item 2 — `test_05::test_the_shared_pool_error_is_reported_while_the_subcap_has_room`
- (a) Subject: the plan-registration cross-field constraint `per_member_removal_subcap ≤ removal_quota_per_cycle` and its code/status.
- (b) Impl paths enumerated (`grep -rn subcap`): `routes/plans.py:14-36` (`PLAN_SPEC` `min: 1` plus the explicit cross-field check raising `ERR_VALUE_OUT_OF_RANGE` before the row is minted — the only write path; no plan-edit endpoint exists); `context.py:129-131` (generic rung-9 raiser, same code); `errors.py:35` (422). Consumers checked so no edit could contradict them: `derive.py:82-87`, `routes/removals.py:99` (rung 46, after the rung-45 pool check), `routes/accounts.py:451-452`, `serializers.py:28`.
- PRD coverage exact and already unique: rung 9 (§2.6 L108) with plan registration in its guarded list; restated §3.1 L208; rungs 45/46 pool-before-sub-cap ordering (L144-145) and §3.5 L280 already pin the property the rebuilt fixture tests.
- (c) No wording adjustment; pure fixture bug.

## Step 9: Complete PRD — 2026-08-08T20:05:00.000Z

`workspace/PRD_COMPLETED.md` written. 525 → 525 lines; 103,295 → 126,084 chars (**+22,789**). 60 lines changed across **57 edit sites**, all in-paragraph inserts/revisions — no new paragraphs, no new sections. Heading diff `diff <(grep '^#' PRD_FINALIZED.md) <(grep '^#' PRD_COMPLETED.md)` → **empty** (orchestrator re-ran it independently: identical). Structural check confirms no table row, code fence, or list marker altered.

**Counts: 50 ambiguity-pins, 7 mismatch-revisions.** (Step 7 clean + Step 8 zero ⇒ Step 9 is the only alignment pass this task got.)

### Mismatch revisions (7)
- **§2.10 Invariant 2** — conservation is scoped to the reappearance path only; a `FRESH` classification at ≥45 days *does* create a second exposure row for the same profile/broker pair — `routes/scans.py:281`
- **§2.11** — "does not skip bumping the rows it touches" is false for finding recording (`findings_count`/`reappearance_hit_count` change with no bump); a cascade bumps the open cycle once *per add-on* — `routes/scans.py:310`, `cascades.py:99,190`
- **§3.3** — `date_of_birth` declared "an ISO 8601 calendar date" but never parsed or checked; stored and echoed verbatim — `routes/profiles.py:42`
- **§3.4** — supplied `exposure_kind`/`source_url` are validated then **discarded** on `REAPPEARANCE`/`RESIGHTING`; a `RESIGHTING` still bumps the exposure's version; ≥45-day `FRESH` creates a second row — `routes/scans.py:281-308`
- **§3.5** — completion hops 2 and 3 **do not fire** when the exposure is not in `FOUND`/`REAPPEARED` (reachable via the escalated-resubmission edge, which does not re-check it) — `cascades.py:276`
- **§3.8** — the "suspend-then-resume round trip is not value-neutral *because of rounding*" claim is wrong: resume books nothing at all (`SEAT_ADDED` fires only at purchase), so the credit stands unreversed — `cascades.py:121`
- **§4** — the 201-on-create rule: finding recording and breach ingest answer **200** even when they create exposure/alert rows — `routes/scans.py:315`, `routes/breaches.py:162`

### Ambiguity pins (50, grouped)
- **§2.1/§2.6 r12** — `Member` role does not require `is_primary` false (`context.py:43`); root-level collection lists apply scope as a *filter* (rows omitted from page and `total_count`), path-parented lists reject (`routes/scans.py:127`).
- **§2.2** — `req_` + 20 uppercase-alnum; `api_request_timestamp` from the logical clock; unknown route/method → `ERR_VALIDATION` at 404/405 (`envelope.py:13`, `app.py:71`).
- **§2.3** — empty `limit`/`offset` → default, non-integer → `ERR_VALUE_OUT_OF_RANGE`; unknown params ignored; full per-endpoint filter catalogue with exact-string semantics; off-enum `kind`/`identifier_type`/`finding_type` → empty page; report arrays unpaginated; `id`-ascending tie-break on every ordering (`context.py:213-249`, `store.py:77`).
- **§2.4** — monotonic ids; clock endpoint echoes literals (`previous_utc` initially exactly `2026-05-01T00:00:00Z`); server-stamped vs caller-echoed instant rendering (`clock.py:1`, `routes/system.py:13`).
- **§2.5** — body-FK resolution order (`addon_id` before `member_id`) (`routes/seats.py:492`).
- **§2.6 r6/r7** — empty/unparseable body, explicit nulls, bool-vs-int, string-length/at-sign/instant-parse all at rung 7 (`context.py:67,163`).
- **§2.6 closing ¶** — **friction 1** (terminal test before transition test; the seven machines with no terminal state) and **friction 2** (rung 32 before rung 35) (`states.py:42`, `routes/removals.py:66`).
- **§2.7** — six non-account-scoped mutations pass no gate; breach ingest still fans out under hold/suspension (`routes/brokers.py:361`, `routes/breaches.py:77`).
- **§2.8** — each of the four OCC'd parents is bumped by its own guarded write (`routes/profiles.py:248`, `seats.py:531`, `accounts.py:325,413`).
- **§2.9** — hygiene/coverage emitted as JSON numbers (`58.0`, `0.0`) (`calc.py:285,393`).
- **§2.10** — `member_id`/`source_reference`/`cycle_id` per reason code; all amounts 1 except grants (`ledger.py:7`).
- **§2.11** — read-time re-derivations bump nothing (`cascades.py:287`).
- **§3.1** — account still `version` 1; `primary_member_email` not @-checked; zero pools with no open cycle; `inv_` token; **PRIMARY uniqueness genuinely unenforced (friction 7)**; invitation bumps the account; token mismatch → `ERR_VALIDATION`; account-ACTIVE via gates 2/3; retirement legs carry full §3.3 effects; released seats start the cool-off; primary removal → `ERR_INVALID_STATE` (`routes/accounts.py:142,390`, `routes/members.py:46,96`, `cascades.py:224`).
- **§3.2** — suspension's add-on branch books the `SEAT_RELEASED` credit and bumps the cycle per add-on; resume books nothing; cancellation order → no successor cycle, add-on cancel books nothing; redundant hold flip and redundant grant/revoke → `ERR_INVALID_STATE` (rung 18 ahead of 21) (`cascades.py:172-219`, `routes/accounts.py:246`, `routes/members.py:71`).
- **§3.3** — `rescan_cadence_days` consulted by **no** endpoint; PATCH has no state precondition and an empty PATCH still bumps; identifiers addable in any status; identifier's five-field projection; `activated_at` not restamped (`routes/profiles.py:100-249`).
- **§3.4** — scan completion bumps the profile; `failure_reason` survives retry; findings answer 200 with the exposure; candidate `id` tie-break (`routes/scans.py:163-315`).
- **§3.5** — broker catalogue ungated, `RETIRED` not terminal, broker row carries the four LIFETIME counts; verify-past-expiry → `ERR_INVALID_STATE`; **friction 3** (rungs 25/26 on stored status, transition applied after, bumping version); incumbent `id` tie-break; **friction 4** (exposure-status precondition enforced as `ERR_INVALID_STATE`, between rung 22 and the identity gate); resubmission overwrites `submitted_by_agent_id`; fields surviving escalation (`routes/removals.py:188-360`, `routes/brokers.py:357`, `routes/documents.py:258`).
- **§3.6** — instants parsed/echoed verbatim, duplicates kept in `record_types`; empty ingest array accepted; `ingest_seq` post-increment; event version bump; ungated fan-out; creation-order alerts; **friction 5** (general monotonicity governs → `MEDIUM→CRITICAL`, `LOW→CRITICAL` admitted) (`routes/breaches.py:29-171`).
- **§3.7** — **friction 8** (`weight` always the per-type penalty); findings recordable against any profile status (`serializers.py:279`, `routes/findings.py:289`).
- **§3.8** — purchase bumps the cycle; only suspension touches a cycle; resume's account-ACTIVE requirement is rung 15; **seat bind does not check the member belongs to the add-on's household**; release/rebind don't bump the add-on; rebind clears `rebind_eligible_at` (`routes/accounts.py:477`, `routes/seats.py:496,576`, `routes/addons.py:433`).
- **§3.9** — closure bumps only the cycle and answers with the closed one; downgrade guard runs on both kinds; **friction 6** (contradictory `change_kind` → no variant, no money, cycle untouched, change still succeeds, answers with the account); `member_breakdown` four-field shape and null-cycle behaviour; `brokers` element shape; `top_offending_profiles` two-field shape using the **max** (not sum) reappearance count, scope-independent (`cascades.py:138`, `routes/accounts.py:289-547`, `routes/members.py:196`, `routes/brokers.py:390`).

### Post-Step-9 verification (orchestrator)
`find implementation test_suite test_helpers -newer results.1.json` → **empty** (Step 9 touched only PRD files). All 8 `results.N.json` still `passed=125 failed=0 rows=125`.

## Pipeline complete — 2026-08-08T20:07:00.000Z

125/125 × 8 rounds · 0 deletions · 0 implementation fixes · 2 test_suite fixes · Step 8 a legitimate zero · Step 9 = 57 edits (50 pins + 7 mismatches).
