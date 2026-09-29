# Worklog — task_2317_digital_ticket_access_control_fraud

## Step 1: Create task directory — 2026-09-01T15:53:01.493Z

Created `tasks/task_2317_digital_ticket_access_control_fraud/` and `tasks/task_2317_digital_ticket_access_control_fraud/workspace/` (pre-allocated name used verbatim; no index scan performed).

## Step 2: Scaffold artifacts generated — 2026-09-01

- `SCAFFOLD.yaml` (§1.0–§1.7): 13 entities, 10 state machines, 3 concurrency rules, 12 calculations, 41 validations, 59 endpoints, 53 errors, 6 roles; `difficulty_level: expert_plus`.
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (§1.8): 9 rule_ids, 28 instances.
- `SCAFFOLD_CORNER_DESIGN.yaml` (§1.9): 9 sections, 87 instances (47 with `test_recipe`, 40 `excluded_because` stubs citing §1.8 instances).
- `scaffold_lint.py`: `VERDICT: clean lint` over 1150 scanned calls.
- Generated from the scenario text plus the skill specification only; no sibling task under `tasks/` was inspected.

### Verbatim subagent summary (Step 2)

All three artifacts are complete and lint-clean.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2317_digital_ticket_access_control_fraud/`)

- `SCAFFOLD.yaml` — §1.0–§1.7, 2635 lines, no design keys present
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` — single key `scaffold_difficulty_design` (§1.8), 3894 lines
- `SCAFFOLD_CORNER_DESIGN.yaml` — single key `scaffold_corner_design` (§1.9), 4854 lines

## Counts

| Artifact | Counts |
|---|---|
| §1.1–§1.7 | 13 entities, 10 state machines, 3 OCC concurrency rules, 12 calculations, 41 validation priorities, 59 endpoints, 53 error codes, 6 roles; `difficulty_level: expert_plus` |
| §1.8 | 9 `rule_id`s / 28 instances (min 2 per rule) |
| §1.9 | 9 sections / 87 instances = 47 real `test_recipe`s + 40 `excluded_because` stubs |

§1.9 per section: entities 10 (10 real), state_machines 12 (6), calculations 12 (5), validations 14 (7), endpoints 8 (5), errors 19 (5), rbac 4 (4), cross_cutting_complexity_layers 7 (4), consistency_model 1 (1).

## Lint verdict (verbatim)

```
Coverage
  §1.5 endpoints declared:    59
  §1.1 entities declared:     13
  §1.8 instances scanned:     28
  §1.9 instances scanned:     47
  Calls scanned (§1.8+§1.9):  1150

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

## Scaffold amendments made while writing §1.9 (ambiguities the tests exposed)

- **Priority 13 vs 17 shadowing:** reconciliation creation now permits `Event.status IN {CLOSED, RECONCILED}` so `ERR_EVENT_ALREADY_RECONCILED` is reachable instead of being masked by `ERR_EVENT_STATE_FORBIDS_OPERATION`; the error catalog condition was updated to match.
- **Pagination location pinned:** added `response_envelope.pagination_envelope_location` — rows are `$.data[N]`, the four pagination fields are in `meta` (`total_count` pre-limit, `has_more = offset + len(data) < total_count`). All pagination captures in both design files now read `$.meta.total_count` / `$.meta.has_more` (the previous `$.data.total_count` form was the only lint failure, 11 hits).
- **Offline-batch counter semantics** pinned earlier in the session (`accepted + denied == item count`, duplicates counted in both `denied_count` and `duplicate_suppressed_count`).
- Corrected the stale `difficulty_level` inline comment to the real element counts.

## Verified invariants

Name uniqueness across the union of both design files (0 duplicates); every `excluded_because.difficulty_instance` resolves to a real §1.8 instance and no stub carries a `test_recipe`; full placeholder closure (every `${var}` in a payload, path or assert is bound by an earlier `captures:` in the same instance); all 53 catalog error codes appear in the design files with none invented; no forbidden concurrency vocabulary in any file. The hard constraint was respected — no sibling task directory was listed, globbed, grepped or read.

## Step 3: Copy shared files — 2026-09-01T17:36:40.914Z

Copied `INSTRUCTION.md` from project root to `tasks/task_2317_digital_ticket_access_control_fraud/workspace/INSTRUCTION.md` (1424 bytes).

## Step 4: Generate PRD — 2026-09-01T17:52:31.381Z

The PRD is complete and all three Hard Contracts pass.

## Output

`/home/ubuntu/github/CodingPRD/tasks/task_2317_digital_ticket_access_control_fraud/workspace/PRD.md` — **437 lines**, titled "Ticket Access Control API — Product Requirements Document".

## Section list

- **§1 Introduction** (3 paragraphs: rotating barcodes + device binding, denials-as-evidence, two head-count readings)
- **§2 Global Specifications & System-Wide Principles** — 2.1 User and Role-Based Access Control; 2.2 API Response Structure (pasted byte-identical from `section-2.2-response-structure.md`); 2.3 Pagination; 2.4 The Logical Clock; 2.5 Common Resource Properties, Timestamps and Versioning; 2.6 Stale-Version Guards on Parent Aggregates; 2.7 Reference Resolution and Same-Event Integrity; 2.8 Money, Rounding and Conservation; 2.9 Fire Code, Occupancy and Two Readings of Attendance; 2.10 Patron Fraud Risk Scoring; 2.11 The Rotating Barcode and Its Acceptance Window; 2.12 Rule Evaluation Order (all 41 priorities as an ordered ladder)
- **§3 Business Logic & Workflows** — 3.1 Standing Up an Event; 3.2 Patron Accounts, Identity and Device Binding; 3.3 Issuing Entitlements at the Box Office; 3.4 Complimentary, Will-Call and Credential Distribution; 3.5 Handing Over an Entitlement; 3.6 Verified Resale, Price Caps and Settlement; 3.7 Gate Operations: Sessions, Scanning and the Offline Cache; 3.8 Denied-Entry Investigation, Remediation and Voiding; 3.9 Post-Event Reconciliation
- **§4 Endpoint Definitions** — 4-column table, 59 rows, plus a filter-parameter trailer
- **§5 Error Code Catalogue** — 2-column table, 53 rows

## Coverage audits

```
Field coverage check:
- entities[].fields: 133 required, 133 present, 0 missing
- endpoints[].request_body (input): 138 required, 138 present, 0 missing
- endpoints[].query_params (list filters): 30 required, 30 present, 0 missing
- endpoints[].path_params: 39 required, 39 present, 0 missing
- endpoints[].output fields: 19 required, 19 present, 0 missing
Status: PASS
```

```
Rule coverage check:
- validations[] with priority: 41 checked, 41 expressed in prose, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + error_id all named), 0 missing
- state_machines[].transitions: 41 checked, 41 fully expressed, 0 missing
- calculations[]: 12 checked, 12 fully expressed, 0 missing
- validations[] conditions: 41 checked, 41 matchable to error_id + HTTP status in the §2.12 ladder, 0 missing
- endpoints[].side_effects / applies_to: 32 checked, 32 expressed, 0 missing
- entities[].fields[] structured content (enums, defaults, nullability): 39 enum groups checked, 39 reconstructible, 0 missing
- sibling-branch symmetry: 5 groups checked (approve/reject, accept/decline, remediate/dismiss, finalize/reopen, purchase/delist), 5 with equal prose density, 0 asymmetric
- errors[]: 53 checked, 53 named in prose and 53 rows in §5, 0 missing
Status: PASS
```

```
Path purity check (§3 only):
- backtick tokens scanned: 747
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
- bare (unbacktick) method words or slash paths in §3: 0
Status: PASS
```

## Notes

- Every rule with contested inclusivity is pinned: the barcode acceptance window as the closed range `[now_epoch − 1, now_epoch]`; the 120-second re-entry lockout as closed at both ends; gate session overlap as half-open `[opened_at, closed_at)` so a session opening exactly at a prior `closed_at` is accepted; credential window overlap as strict so touching windows do not collide; posture thresholds at 1.00 and 0.90 inclusive; the fraud block at strictly below 40.
- The `ERR_GATE_NOT_SCANNING` (priority 11) placement above `ERR_SESSION_NOT_OPEN` (priority 15) is stated with its rationale, as is `ERR_EVENT_STATE_FORBIDS_OPERATION` letting `RECONCILED` pass so `ERR_EVENT_ALREADY_RECONCILED` stays reachable, and `ERR_GATE_SESSION_OVERLAP` owning the second-session case instead of `ERR_INVALID_STATE`.
- Percentage literals are written both as decimals and words (`0.0725`/7.25 percent, etc.) so the settlement split, price cap and goodwill tiers reconstruct unambiguously; per-component round-half-up before summation is stated explicitly.
- Both forbidden files (`SCAFFOLD_DIFFICULTY_DESIGN.yaml`, `SCAFFOLD_CORNER_DESIGN.yaml`) were never opened, grepped or referenced, and no sibling task directory was read.

## Step 5: Generate unit tests — 2026-09-01T19:49:58.171Z

Generation is complete.

## Files written

`test_helpers/` (9 modules): `__init__.py`, `constants.py`, `types.py`, `api_errors.py`, `test_users.py`, `api_client.py` (one method per declared endpoint), `factories.py`, `fixtures.py`, `assertions.py`.

`test_suite/` (`conftest.py` + 18 test modules):
- Queue A (depth index, §1.8): `test_01_occupancy_and_fraud_variants.py` (4), `test_02_money_formulas.py` (8), `test_03_lifecycle_state_machines.py` (6), `test_04_cascades.py` (6), `test_05_rule_priority.py` (6), `test_06_boundaries.py` (6), `test_07_cross_entity_state.py` (8), `test_08_temporal_overlap.py` (6), `test_09_compensating_invariants.py` (6)
- Queue B (breadth index, §1.9): `test_10_entity_contracts.py` (9), `test_11_state_transitions.py` (6), `test_12_derived_calculations.py` (5), `test_13_validation_rules.py` (7), `test_14_endpoint_behaviour.py` (7), `test_15_error_catalogue.py` (5), `test_16_access_control.py` (4), `test_17_concurrency_and_thresholds.py` (4), `test_18_immediate_consistency.py` (1)

## Counts

- **104 tests total: queue A 56, queue B 48.** All 104 carry exactly one `Design:` tag as the docstring's last line; 74 distinct tags.
- Queue A: 28/28 non-stub instances covered. Queue B: 46/47 non-stub instances covered (1 skipped).

## Skipped instance (1)

`Corner/entities/ticket_creation_rejects_client_supplied_system_fields` — the design expects `ERR_INVALID_REQUEST` (400) for a body carrying `barcode_seed`/`lifecycle_status`. PRD rule 3 constrains only required fields, enum membership, integer ranges and timestamp parseability; nothing forbids unknown properties, so the asserted outcome is not uniquely derived. No placeholder, xfail or weakened test emitted.

## Design deviations applied (PRD wins)

- Offline-batch duplicate and zone-violation limbs: tickets end `DENIED_FLAGGED`, not the design's `INSIDE`/`NOT_ADMITTED` (PRD line 282); capacity refusals do leave presence untouched.
- `denied_reason_code` values carry the `ERR_` prefix (line 270).
- `errors/…variance_gate…`: the open scan session is closed before `IN_PROGRESS → CLOSED`.
- `occ_reconciliation_report_rejects_a_stale_event_version`: the event needs both a zone and a gate to leave `DRAFT`.
- `fraud_block_threshold…`: Bob's second strike is taken on a second ticket (a third scan of the same ticket would be `ADMITTED`, since `DENIED_FLAGGED` is not `INSIDE`); each patron got one unscanned spare ticket to list, because listing requires `admission_status` `NOT_ADMITTED`; the blocked transfer is attempted with the clock inside the transfer window, since rule 14 outranks rule 28.
- Audit-trail instance: 3 rows, not 2 (voiding a listed ticket also appends `RESALE_LISTING_SUSPENDED`), and ordering is asserted via non-increasing `occurred_at` plus the oldest row's identity because the logical clock leaves ties.
- Transfer bodies use `to_patron_id` (the design's `recipient_patron_id` is not the declared field).

## Coverage audit

- `python3 /tmp/audit_prd.py -t` → `problems: 0`: every `PRD: "…"` quotation greps verbatim against `workspace/PRD.md`, every test has ≥1 quotation and exactly one trailing `Design:` tag.
- Instance-to-tag reconciliation: no missing non-stub instances except the one skip above, no tags pointing at stub/excluded instances, no unknown tags, no dual tags.
- `python3 -m pyflakes test_suite/*.py` clean; all modules import cleanly; no emitted file mentions "scaffold".

## Step 6: Generate implementation — 2026-09-01T19:49:58.171Z

Implementation complete and verified booting + running end-to-end.

## Files written (all under `/home/ubuntu/github/CodingPRD/tasks/task_2317_digital_ticket_access_control_fraud/workspace/implementation/`)

Infrastructure
- `start.sh` — guarded dependency install, then `exec python3 app.py` (foreground)
- `requirements.txt` — `Flask==3.0.3`
- `app.py` — app factory, `strict_slashes=False`, `ApiError`/`HTTPException`/catch-all handlers that always emit the PRD envelope, a global `RLock` acquired in `before_request` and released in `teardown_request`, `app.run(host="0.0.0.0", port=int(os.environ.get("PORT","10000")), threaded=True)`
- `db.py` — in-memory `Store` (13 plain dicts, logical clock, `_seq` counter); **boots empty, nothing seeded**; `base_record`/`touch`/`public`/`sort_created_asc`
- `util.py`, `errors.py` (all 53 error ids → HTTP), `response.py` (envelope + list meta), `middleware.py` (auth ladder rules 1–2, body/query validators, pagination)

Services
- `services/calc.py` — all 12 calculations (rotating barcode, zone posture, price cap, settlement split, forgone revenue, remediation credit, dual-variant fraud score, reconciled attendance, clearance projection, variance, lockout, window overlap)
- `services/domain.py` — lookups, audit trail, zone-posture recompute, fraud rescore, the incident → strike → rescore → listing-suspension → ticket-revert cascade, ticket minting

Routes (`routes/__init__.py` registers 12 blueprints)
`clock.py` 1, `events.py` 6, `zones.py` 3, `gates.py` 3, `patrons.py` 4, `tickets.py` 7, `transfers.py` 5, `listings.py` 5, `credentials.py` 7, `sessions.py` 8 (sessions + live scan + offline batch + scan-event reads), `incidents.py` 5, `reports.py` 5.

## Endpoint count
**59 implemented — an exact set-match against the PRD §4 table** (verified programmatically over `app.url_map`: 0 missing, 0 extra).

## start.sh / port contract
`start.sh` never hardcodes a port: it `cd`s to its own directory, installs Flask only if `import flask` fails (so per-test reboots are fast and don't contend on pip), then `exec python3 app.py`, replacing the shell so the server is PID-foreground and the script never exits early. `app.py` reads `PORT` from the inherited environment (default `10000`) and binds `0.0.0.0`. Verified with `PORT=10999 bash start.sh`: `ss -ltnp` showed `LISTEN 0.0.0.0:10999`.

## Verification
Two smoke suites (~110 assertions, 0 failures) exercised: clock moves; event/zone/gate setup with duplicate-code and cross-event guards; status ladder incl. `ON_SALE` prerequisites and `CLOSED` blocked while a session is open; patron registration/verification with case-insensitive email uniqueness; issuance with pool/entitlement counters; transfer offer/accept (binding released, competing offers declined); resale with STATUTORY cap, self-purchase refusal and the exact settlement split (319/154/158/3769 on 4400); credential draft→submit→approve with SoD refusal and auto-minted tickets; device binding and barcode epochs; session open with OCC + overlap guard; ADMITTED / EXIT_RECORDED / DENIED_DUPLICATE / DENIED_COUNTERFEIT / DENIED_STALE_BARCODE / DENIED_DEVICE_MISMATCH / DENIED_ZONE / DENIED_CAPACITY / DENIED_REENTRY_LOCKOUT with persist-then-error semantics; rule-10 voided live scan persisting nothing; dedupe-key rejection; `ERR_GATE_NOT_SCANNING` after close; offline batch (`accepted/duplicate_suppressed/denied` + `SYNCING`); incident review/remediate (credit 10500 = 10000 + 1500 − 1000) and dismiss with strike withdrawal; occupancy dual readings (live 0 / reconciled 1 after an exit); reconciliation cut, tolerance refusal, override finalize → `RECONCILED`, `ERR_EVENT_ALREADY_RECONCILED`, reopen; audit log ordering and filters.

Two judgement calls worth flagging: (1) a barcode with a **negative** epoch index (clock before `barcode_anchor_at`) would be unsplittable under a naive "split at last hyphen", so `split_barcode` recognises the trailing-hyphen/negative-digits form while keeping PRD semantics for normal tokens; (2) per rule 33 and the scaffold, only `COMP`/`CREDENTIAL` listings return `ERR_TICKET_NOT_TRANSFERABLE` — a `WILL_CALL` listing is refused with `ERR_INVALID_STATE` (the PRD names the specific error only for the give-away types).

## Step 7: Run tests and iterate — 2026-09-02T07:09:21.763Z

All 8 parallel rounds are green: 104/104 passed, 0 failed, 0 errors in every round.

## Summary

**Iterations run:** 5 full 8-round parallel sweeps plus 24 gated retry attempts of the sweep (the retries were needed only because the host was saturated by peer agents at load 300–450, which made the runner's own per-test port-teardown `lsof` call time out; every non-pass in those attempts was that harness error, never an assertion). Final sweep: `results.1..8.json` all report `total 104, passed 104, failed 0, errors 0`.

**Tests deleted:** none. No test failed STEP 1a/1b — every failing assertion traced to verbatim PRD prose and was uniquely determined by it.

**Fixes applied to `test_helpers/`:** none. No fixture, factory, or role-header builder was found inconsistent with PRD.

**Fixes applied to `implementation/`:**

1. `/home/ubuntu/github/CodingPRD/tasks/task_2317_digital_ticket_access_control_fraud/workspace/implementation/util.py` — added `iso_clock(dt)`, a renderer for logical-clock instants that emits second precision (`2026-08-01T00:00:00Z`) and only grows a fractional part if the client moved the clock to a sub-second instant. `iso3()`/`now_iso3()` were left untouched because PRD §2.5 and §2.2 mandate three fractional digits specifically for `created_at`/`updated_at`/`api_request_timestamp`.

2. Switched every logical-clock render site from `iso3(db.clock)` to `iso_clock(db.clock)` — `routes/clock.py` (`current_utc`, `previous_utc`), `services/domain.py` (`occurred_at` on audit entries), `routes/transfers.py` (`decided_at`), `routes/sessions.py` (`opened_at`, `closed_at` incl. the copy into `gate["last_session_closed_at"]`, `recorded_at`, and the `scanned_at` default; `last_admitted_at`/`last_exited_at` inherit from `recorded_at`). Governed by PRD §2.4: "Endpoints that record a server-side instant — `opened_at` and `closed_at` on a scan session, `recorded_at` on a scan event, `decided_at` on a transfer decision, `occurred_at` on an audit entry — take the logical clock's value at the moment of the write," combined with "the logical clock reads exactly `2026-08-01T00:00:00Z`". This single root cause accounted for 16 of the 16 genuine failures (15 tripping `assert '<instant>.000Z' == '<instant>Z'`, the 16th the offline-batch `recorded_at` genexpr).

3. `routes/reports.py::reopen_report()` — removed the `RECONCILIATION_REOPENED` audit entry. PRD §8.5 enumerates the verbs this system writes and does not include a reopen verb, and the reopening paragraph names no audit entry among its effects; the row violated the "never add a side effect that does not trace to a verbatim PRD sentence" rule. The `reason` field is still required, as PRD says reopening "takes a `reason`".

Also verified: storage remains in-memory dicts with no startup seeding (`db.Store.reset()` creates empty dicts only), and the registered route table is an exact 1:1 match with the 59 endpoints in the PRD §7 table (plus Flask's built-in `/static`).

## Step 8: Finalize PRD — 2026-09-02T07:14:38.109Z

PRD_FINALIZED.md is written. Summary below.

## Line counts
- `PRD.md`: 436 lines; `PRD_FINALIZED.md`: 438 lines (+2 lines, +0.46%). Two edit sites: one inserted paragraph in §2.4, one revised sentence in §3.9.

## Changes
- **§2.4 (The Logical Clock) — insert — logical-clock instants render at the clock's own precision (whole seconds + `Z` at `2026-08-01T00:00:00Z`, three fractional digits only when the client moved the clock to a sub-second instant), normalized to UTC; `current_utc`/`previous_utc`, the defaulted `scanned_at`, and mirrored fields render the same way; client-supplied instants are echoed verbatim; `created_at`/`updated_at`/`api_request_timestamp` are stamped from real server time in the three-digit shape and nothing time-dependent is evaluated against them** — `implementation/util.py:51-70` (`iso_clock`), `routes/clock.py:18-20`, `routes/sessions.py:67,107,113,133,285`, `routes/transfers.py:108,139`, `services/domain.py:76`, `db.py:48,59`.
- **§3.9 (Post-Event Reconciliation, Reopening) — revise — `reason` is mandatory and non-empty, is stored on no report field, and reopening appends no audit entry (no reopen verb in the §3.1 vocabulary)** — `implementation/routes/reports.py:118-141`.

## Per-edit pre-edit search log

**Edit 1 — §2.4 clock-instant rendering**
- (a) Subject: how any instant the server sources from the logical clock is serialized, versus instants sourced from real time or from client input.
- (b) Paths enumerated (grepped `iso3|iso_clock|now_iso|f_dt|created_at|updated_at|_at"] =` across `implementation/`, then read each site): `util.py::iso_clock`/`iso3`/`now_iso3`/`parse_dt`; `db.py::Store.reset` (clock boots at `parse_dt("2026-08-01T00:00:00Z")`, microsecond 0), `db.py::base_record`/`touch` (only `created_at`/`updated_at` writers, both `now_iso3` = wall clock); `response.py:11` (`api_request_timestamp` = `now_iso3`); `routes/clock.py` (`current_utc`, `previous_utc`, both `iso_clock`, `astimezone(UTC)` handles non-UTC input offsets); `routes/sessions.py` (`opened_at`, `closed_at`, the copy into `gate["last_session_closed_at"]`, `recorded_at` on both live and offline-batch persists, and the `scanned_at` default — client-supplied `scanned_at` is stored raw via `f_dt`, which documents "input instants are echoed verbatim"); `sessions.py::_apply_effects` (`last_admitted_at`/`last_exited_at` = `scan["recorded_at"]`, so they inherit the clock render); `routes/transfers.py:108,139` (`decided_at` on accept, on cascaded declines, and on decline); `services/domain.py::append_audit` (`occurred_at`); `routes/events.py:51-54` and `routes/credentials.py:51-52` (client instants stored raw — the only other `*_at` writers); `routes/tickets.py::read_barcode` and `routes/gates.py:43` (no clock-rendered instants). Also confirmed `created_at` is used only as a sort key (`db.py:69`, `sessions.py:407`, `events.py:152`), never in a temporal comparison.
- (c) Adjustments: dropped an initial universal phrasing "instants supplied by a client are echoed back verbatim" in favour of "an instant that a client supplies **for storage on a record**", because `to_iso8601` is *not* echoed verbatim (it is normalized to UTC through the clock render) — the unqualified version would have contradicted `routes/clock.py`. Added the explicit non-UTC-offset clause to match `astimezone(UTC)`. Phrased the fractional rule as "the millisecond part … only once the clock carries a non-zero fraction of a second" to match `iso_clock`'s truncating `microsecond // 1000` (a sub-millisecond clock value still prints `.000Z`). Kept §2.4's existing "never falls back to real time" claim intact by scoping the real-time stamping strictly to the three bookkeeping fields and adding "no deadline, window, lockout or acceptance interval is ever evaluated against them".

**Edit 2 — §3.9 reopening**
- (a) Subject: the side effects of `POST /reconciliation-reports/{id}/reopen` — specifically its `reason` field and whether it writes to the audit trail.
- (b) Paths enumerated: `routes/reports.py::reopen_report` (`f_str(..., "reason", allow_empty=False)`, required by default; sets `status`/`finalized_by_user_id`, touches report and event; no `append_audit`), `routes/reports.py::create_report`/`finalize_report` (report field set never contains `reason`; only finalize writes `RECONCILIATION_FINALIZED`), `services/domain.py::append_audit` and every `append_audit` callsite (`credentials.py`, `tickets.py`, `listings.py`, `incidents.py`, `reports.py`) — confirmed no reopen verb is emitted anywhere; `routes/tickets.py::void_ticket` (the other `reason` field, which *is* consumed — folded into the audit `detail`), so the claim had to stay reopen-local.
- (c) Adjustment: scoped "records it nowhere" to reopening only rather than making a general statement about `reason` fields, since the void endpoint's `reason` does surface in that audit entry's `detail`; and grounded the no-audit claim in the existing §3.1 verb list rather than asserting a new prohibition.

## Step 9: Complete PRD — 2026-09-02T07:24:21.512Z

Done. `PRD_COMPLETED.md` written.

## Counts

- **Source** `PRD_FINALIZED.md`: 438 lines / 84,664 chars
- **Result** `PRD_COMPLETED.md`: 438 lines / 90,069 chars → **char-delta +5,405**, line-delta 0 (all changes are in-paragraph; no new sections or paragraphs)
- **24 changes**: **18 ambiguity-pins**, **6 mismatch-revisions**

## Changes

- §2.3 Pagination — insert — ambiguity — out-of-range/non-integer `limit`/`offset` → `ERR_INVALID_REQUEST` (400); empty string falls back to default — `middleware.py:135-154`
- §2.5 Versioning — insert — ambiguity — report finalize/reopen also bump event `version`; forced gate→`IDLE` at event `CLOSED` bumps nothing; ticket `version` also moves on resale purchase, fraud suspension and void — `reports.py:100-103,129-135`, `events.py:107-111`, `listings.py:166`, `tickets.py:149`, `domain.py:123-125`
- §2.6 (rule 9 ref) §2.12 rule 9 — insert — ambiguity — transfer accept / listing create / live exit raise `ERR_INVALID_STATE` for the referenced *ticket*, positioned lower than rule 9 — `transfers.py:102`, `listings.py:55-60`, `sessions.py:271`
- §2.9 Occupancy read — insert — ambiguity — `headroom` may go negative; `zone_occupancy` ordered `created_at` ascending — `events.py:128-138`, `domain.py:32-33`
- §2.11 Barcode split — revise — mismatch — negative-index refinement (`SEED--3` → seed `SEED`, epoch `-3`); a seed resolving to another event's ticket is also `DENIED_COUNTERFEIT` — `calc.py:76-86`, `sessions.py:248`
- §2.12 rule 3 — insert — ambiguity — required string fields must be non-empty/non-whitespace; optional strings may be empty — `middleware.py:51-61`
- §2.12 rule 10 — revise — mismatch — `ERR_TICKET_VOIDED` does **not** guard offline batch upload; items adjudicate to `DENIED_VOIDED` — `sessions.py:201-203,252-253`
- §2.12 rule 32 — revise — mismatch — also applies to the resale *seller* on listing creation — `listings.py:51-52`
- §3.2 Identity — insert — ambiguity — re-verifying an already-verified patron is accepted and bumps `version` again — `patrons.py:60-68`
- §3.2 Device binding — insert — ambiguity — release declared only from `BOUND` (else `ERR_INVALID_STATE` 409) and has no voided-ticket guard — `tickets.py:119-130`
- §3.3 Issuance — insert — ambiguity — zero `face_value_cents` on `COMP`/`CREDENTIAL` is a convention, not validated — `tickets.py:33,52-53`
- §3.5 Acceptance — insert — ambiguity — ticket lifecycle outside `ISSUED`/`TRANSFERRED` → `ERR_INVALID_STATE` (409), evaluated last — `transfers.py:102-106`
- §3.6 Listing gates — revise — mismatch — pinned clause order plus error ids: unverified seller → `ERR_RECIPIENT_NOT_VERIFIED`; `WILL_CALL` → `ERR_INVALID_STATE`; admitted ticket → `ERR_INVALID_STATE`; already `LISTED`/`RESOLD` → `ERR_INVALID_STATE` — `listings.py:43-60`
- §3.6 Unverified marketplace — insert — ambiguity — the `UNAUTHORIZED_RESALE` incident carries a null `scan_event_id` — `listings.py:64-66`
- §3.6 Price cap — insert — ambiguity — `cap_price_cents` is null under the `NONE` regime — `calc.py:130-131`, `listings.py:85`
- §3.6 Suspension — revise — mismatch — a void suspends only the voided ticket's own `LISTED` listing (not every listing of that seller); the ≥40 path suspends all — `tickets.py:151-161` vs `domain.py:102-126`
- §3.7 ScanEvent shape — insert — ambiguity — `ticket_id` also null for a cross-event seed; row echoes `presented_barcode`, `device_fingerprint`, `direction`, `dedupe_key`, `scanned_at` verbatim — `sessions.py:124-141`
- §3.7 Result values — revise — mismatch — "eleven" → "ten"; both fire-code refusals share `DENIED_CAPACITY`, distinguished only by `denied_reason_code` — `sessions.py:25-33,276-279`
- §3.7 Exit scan — revise — mismatch — `OUT` still runs rules 20-22 and 25; only 23, 24, 26, 27 are entry-only; live exit on a non-`INSIDE` ticket → `ERR_INVALID_STATE` (409) persisting nothing; occupancy decrements floored at zero — `sessions.py:210-227,271-272`, `sessions.py:177-179`
- §3.7 Offline upload — insert — ambiguity — whole-array shape validation aborts the upload with `ERR_INVALID_REQUEST` before the session/gate/mode/event guards; item `dedupe_key` is not uniqueness-tested but is registered against the session — `sessions.py:302-334`, `sessions.py:143`
- §3.7 Offline adjudication — insert — ambiguity — offline exits set `EXITED` and `last_exited_at` from the logical clock without moving occupancy, and a non-`INSIDE` exit item is still recorded `EXIT_RECORDED` — `sessions.py:171-181,353-355`
- §3.8 Remediation — insert — ambiguity — null `ticket_id` → `ERR_INVALID_STATE` (409), tested before the pool check — `incidents.py:57-68`
- §3.8 Dismissal — insert — ambiguity — `strike_count` never falls below zero — `incidents.py:107`
- §3.8 Voiding — insert — ambiguity — both entitlement counters floored at zero; refund has no pool-sufficiency guard so `settlement_pool_cents` may go negative — `tickets.py:163-171`
- §3.9 Finalization — insert — ambiguity — `override_reason` persisted only when non-empty; figures recomputed *before* the tolerance test, so a refused finalize leaves recomputed figures but unchanged `status`/`version`/`updated_at` — `reports.py:91-96`

Verified-consistent and left untouched: the full §2.12 ladder ordering per endpoint, all §4 role assignments and status codes, all money formulas (settlement split, price cap, forgone revenue, remediation credit), fraud-score dual readings, posture thresholds, credential window-overlap capacity, re-entry lockout boundary, list filters and sort orders, and the §5 error catalogue.

---

## Pipeline complete

All nine steps finished. Final state: `workspace/PRD_COMPLETED.md` on disk; `results.{1..8}.json` in `workspace/implementation/` all reporting 104/104 passed.
