# Worklog — task_0932_registered_agent_compliance_calendar

Scenario (verbatim from user):
> 932. Registered-Agent & Compliance-Calendar Service: entity & state registration, agent-of-record & service-of-process forward, annual-report & franchise-tax calendar, filing & fee, BOI/beneficial-owner filing, foreign-qualification, dissolution, multi-state portfolio

Difficulty: **beyond-Expert** (user asked "generate task hard than expert level!").

Host note: a concurrent pipeline (task_0931) started at 15:59:40Z on this 8-core host — sweeps must stay capped (waves of 4) per the host-saturation playbook.

## Step 1: Create task directory — 2026-08-08T16:00:20.000Z

Created `tasks/task_0932_registered_agent_compliance_calendar/workspace/` (index 0932, next after 0931).

## Step 3: Copy shared files — 2026-08-08T16:00:20.000Z

Copied `INSTRUCTION.md` → `tasks/task_0932_registered_agent_compliance_calendar/workspace/INSTRUCTION.md` (done early alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-08T16:55:00.000Z

All three scaffold artifacts written to `tasks/task_0932_registered_agent_compliance_calendar/`.

### Structural counts

| Dimension | Value | Target |
|---|---|---|
| Entities | **17** | 15–18 OK |
| Endpoints | **75** | 60–75 OK |
| Error codes | **40** | 30–40 OK |
| Calculations | **27**, of which **8 dual-variant** | 18–24 / 6+ (over on total, by helper/invariant calcs, not padding) |
| State machines | **11** (on 10 entities; `LegalEntity` carries two), **10 non-linear** | 8+ / >=4 OK |
| Validation ladder | **42 ordered rungs** | 30+ OK |
| OCC rules | **3** (`filing-create-stale-obligation`, `agent-appointment-create-stale-registration`, `boi-report-create-stale-entity`) | 2–3 OK |
| Conservation invariants | **4** (`client_funds_identity` money; `portfolio_rollup` count+cents; `agent_of_record_selector` exactly-one-of-record cardinality; `ReinstatementCase.obligations_cured_count == missed_period_count`) | 3+ OK |
| Deepest cascade | **5 hops** — `Filing -> ComplianceObligation -> Registration -> LegalEntity -> Client` off `POST /filings/{id}/record-outcome` (ACCEPTED) | 5 OK |
| Extra | 9 `gate_precedence` blocks, 5 roles (segregation of duties), 41 declared constants | |
| Design files | 18 difficulty instances (2 x 9 rules), 78 corner instances (68 with recipes + 10 `excluded_because` stubs) | |

### Self-audits

**A. Incremental writing** — every file authored in bounded appends (10 chunks for `SCAFFOLD.yaml`, 4 for the difficulty design, 5 for the corner design). No oversized single write; no truncation.

**B. YAML lint** — `yaml.safe_load` run after every chunk and once more at the end: all three clean. Two real offenders caught and fixed: bare `?` inside flow sequences (`input: [state_code?, ...]` -> quoted, 75 endpoint lines rewritten), and nested `[` inside flow items (`grounds: [errors[ERR_X]]` -> quoted, 10 lines). Also ran `scaffold_lint.py` — verdict pasted verbatim:

```
Coverage
  §1.5 endpoints declared:    75
  §1.1 entities declared:     17
  §1.8 instances scanned:     18
  §1.9 instances scanned:     68
  Calls scanned (§1.8+§1.9):  771

VERDICT: clean lint — all §1.8/§1.9 calls conform to §1.5 and all §1.1 FKs have reverse-reachability in §1.5.
```

**C. Undeclared constants** — **41 global constants + per-calculation blocks = 42 declared; 0 undeclared.** Regex sweep for `*_DAYS|_HOURS|_CENTS|_WINDOW|_THRESHOLD|_BUFFER|_CAP|_RATE|_FEE|_BPS|_LEVEL|_DATE|_COUNT|_PCT|_UTC|_HOLIDAYS|_OFFSETS` found 30 constant-shaped tokens, all resolved (3 apparent hits were enum members `CALENDAR_DAYS`/`BUSINESS_DAYS`/`FIXED_CALENDAR_DATE`, not constants). Every global constant has a non-null value. Per-jurisdiction numbers deliberately live as `StateRule` row fields (input data with declared defaults), not constants.

**D. Reachability audit** — all 40 error codes are referenced by >=1 validation/transition and each has a concrete producing chain (verified against the design files). Automated enum-closure sweep found **one gap and it was self-repaired**: `ReminderNotice.offset_label` values `T_MINUS_90/60/30/7` were only derivable from a string-concatenation expression (`"T_MINUS_" + str(offset)`), so `reminder_schedule` was rewritten to enumerate the five labels literally. Arithmetic-feasibility checks: `VOLUME_DISCOUNT_THRESHOLD = 5` is reachable (5 distinct `(registration, type, period_year)` combos on one registration); `MAX_REFILE_ATTEMPTS = 3` and `SOP_MAX_ESCALATION_LEVEL = 3` are both crossable; `SOP_RISK_FLAG_THRESHOLD = 2` is reached at escalation 2. Pre-emption check: `ERR_FINAL_REPORT_OUTSTANDING` (rung 29) sits behind `ERR_ACTIVE_REGISTRATIONS_EXIST` (rung 28), and is still reachable because `TERMINATED` deliberately does *not* void `FINAL_REPORT` obligations — corner instance `corner_final_report_obligation_survives_termination_and_blocks_dissolution` drives it. All grounds references machine-checked: **0 unresolved** across 96 instances; **0 duplicate instance names**.

**E. Gate precedence explicit** — a dedicated `gate_precedence:` block declares ordered gates for 9 operations (foreign-qualification, terminate, dissolve, capture, submit, refile, escalate, BOI submit, obligation create). Two orderings are deliberately counter-intuitive and stated: dissolve puts the *referential* sweep before the *safety* gate, and foreign-qualification puts home-state delinquency before certificate freshness.

**F. Domain-seam coverage** (all 12 modelled):
1. Per-jurisdiction divergence — `StateRule` (33 fields), `franchise_tax_amount`, `late_fee_amount`, `annual_report_due_date`, `grace_end_date`.
2. Effective-dated rule versions — `governing_state_rule_selection`, `ComplianceObligation.governing_rule_id` (pinned, never re-resolved), rungs 18/19, `POST /registrations/{id}/calendar-rebuild`.
3. Calendar arithmetic — `observed_business_day_roll_forward`, day-clamping, `grace_basis` calendar-vs-business, strict `<` in `good_standing_freshness`.
4. SOP forward — `sop_forward_deadline` (business hours), `sop_ack_deadline`, `sop_escalation_channel`, `sop_deferral_on_litigation_preemption`, rungs 38/39.
5. Agent-of-record transitions — `agent_of_record_selector` (priority_rank keeps the resigning agent of record through the 30-day window), `AgentAppointment` machine, rung 31.
6. Filing & fee — `filing_fee_breakdown`, `payment_allocation_waterfall`, `refund_split_on_rejection`, rungs 33–37, `Payment`/`PaymentAllocation`.
7. BOI — `boi_initial_deadline` (3 formation bands), `boi_update_deadline` (30-day re-arm), `boi_exempt_class`, `company_applicant_required`, rungs 40/41.
8. Foreign qualification — `good_standing_freshness`, `NameClearance` + DBA fallback, rungs 23/24/25.
9. Dissolution / withdrawal — rungs 26–29, `Registration.ACTIVE_to_TERMINATED` (final report survives), `LegalEntity.WINDING_DOWN_to_DISSOLVED`.
10. Reinstatement — `reinstatement_back_fee_total` (period-rule vs current-rule dual variant), `reinstatement_window_close_date`, rung 42, `ReinstatementCase` machine.
11. Notice ladder — `reminder_schedule` (T-90/60/30/7/OVERDUE, idempotent, suppressed, re-armed), `ReminderNotice` machine.
12. Portfolio rollup — `portfolio_rollup`, `registration_delinquency_rank`, `GET /clients/{id}/portfolio-summary`, `Client.portfolio_*` fields.

### One design decision worth flagging

`api_prefix` is set to `""` and every endpoint path parameter is the literal `{id}`. This is required by `scaffold_lint.py` check (f), whose sub-resource form matches `<prefix>/<segment>/{id}/...` verbatim — descriptive parameter names (`{client_id}`, `{legal_entity_id}`) made all 12 sub-resource FK reverse-reachability checks fail. No path in the scaffold carries more than one parameter, so `{id}` is unambiguous. Validation rungs 4–11 name the owning collection explicitly (`the {id} segment under /clients`) rather than relying on the parameter name.

### Orchestrator independent verification

- `yaml.safe_load` on all three files: OK (3954 / 1451 / 3253 lines).
- Section counts re-derived from parsed YAML: 17 entities, 11 state machines, 3 concurrency rules, 27 calculations, 42 validations, 9 gate_precedence blocks, 75 endpoints, 40 errors, 5 roles, 41 constants.
- Independent constant sweep: 0 constant-shaped ALL_CAPS tokens undeclared (only `BUSINESS_DAYS` / `CALENDAR_DAYS`, both enum members); 0 null-valued constants.

## Step 4: Generate PRD — 2026-08-08T17:15:00.000Z

PRD complete at `workspace/PRD.md` — 663 lines, authored in 15 bounded writes, ending at §5 with no audit footer.

**Structure:** §1 intro (3 paras) · §2 with 12 subsections (2.1 roles/identity, 2.2 verbatim envelope, 2.3 pagination+ordering, 2.4 identity/versioning, 2.5 logical clock + business calendar + business-hour cursor, 2.6 effective-dated rules, 2.7 money + 4 conservation invariants, 2.8 OCC, 2.9 the 42-rung ladder + 2.9.1 the 9 gate-precedence blocks, 2.10 path resolution, 2.11 rank/rollups, 2.12 cascades incl. the depth-5 chain) · §3 with 13 workflow subsections · §4 75-row table · §5 40-row table.

**Hard Contracts**
```
Field coverage check:
- entities[].fields: 164 required, 164 present, 0 missing
- endpoints[].request_body/input: 93 required, 93 present, 0 missing
- endpoints[].query_params/path_params: included in the 93 above, 0 missing
Status: PASS

Rule coverage check:
- validations[] with priority: 42 checked, 42 expressed in prose (each with ordinal, applies_to and error id), 0 missing
- gate_precedence[] blocks: 9 checked, 9 expressed as ordered checks, 0 missing
- concurrency_rules[] OCC rejections: 3 checked, 3 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION/412), 0 missing
- state_machines[].transitions: 11 machines / 63 transitions checked, 63 fully expressed incl. failing branches, 0 missing
- calculations[]: 27 checked (8 dual/multi-variant, every variant rendered), 27 fully expressed, 0 missing
- validations[] conditions: 42 checked, 42 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 75 checked, 75 expressed, 0 missing
- entities[].fields[] structured content: 164 checked (types, defaults, ranges, initial values, response-exposure), 164 reconstructible, 0 missing
- sibling-branch symmetry: 14 groups checked, 14 with equal prose density, 0 asymmetric
Status: PASS

Path purity check (§3 only):
- backtick tokens scanned: 1379
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

**Consistency check (a)–(e)**
- (a) All 42 rungs appear with ordinal position (`**Rung 1**`…`**Rung 42**`) — 0 missing.
- (b) All 40 error codes appear in a sentence stating when they are returned, all of them outside §5 — 0 table-only.
- (c) All 75 endpoints appear with request shape, success response and dominant error paths; the 25 read/list endpoints additionally got explicit response-content sentences.
- (d) All 41 constants appear with numeric values (24 holiday dates enumerated; `4900`/`735`/`4165`, `5000`/`12500`/`30000`, `1500` bps, `9`/`17`/`8` hours, `16`/`4`/`8`/`4`/`3`/`8`/`2` SOP, `90`/`60`/`30`/`7`/`1` reminders, `30`/`15`/`3`, `2024-01-01`/`2025-01-01`/`90`/`30`, ranks `0`–`4`, `2026-05-01T00:00:00Z`).
- (e) No "described above/below" without the rule being stated; all cross-references are numbered Section pointers resolving to existing sections.

**Un-adjudicated friction points (13)**

- FRICTION 1: §2.4/§2.5 `created_at`/`updated_at` source — logical-clock instant (the clock "never falls back to wall-clock time") vs. server wall clock. Consequential because rule-selection, waterfall and list tie-breaks all key on `created_at`; under the logical clock many rows share a stamp.
- FRICTION 2: §2.3 list tie-break — rows sharing `created_at` ordered by insertion order vs. by `id`; the scaffold pins no tie-break for generic lists.
- FRICTION 3: §3.1 portfolio summary — `worst_state_code` when two registrations tie on the highest `delinquency_rank`, and whether `registration_count` counts every status or only occupied ones. Neither is pinned.
- FRICTION 4: §3.4 `due_date` for `BOI_INITIAL`/`BOI_UPDATE`/`FINAL_REPORT` obligations — the state-rule due-date formula applies to every type without branching, vs. the reading that beneficial-ownership rows should take the entity's `boi_initial_deadline`/`boi_update_deadline`.
- FRICTION 5: §3.7 expedite state surcharge on an obligation-backed filing — `expedite_surcharge_cents` from the obligation's pinned `governing_rule_id` vs. from the rule effective on the filing's creation date (rung 18 does not list this endpoint).
- FRICTION 6: §3.7 refile — whether the successor's breakdown re-prices the obligation's `late_fee_cents` at the refile date (late-fee trigger says "every filing creation against an obligation") vs. reuses the stored components (the refile side-effect list omits the recompute the obligation-backed draft states explicitly).
- FRICTION 7: §3.7 the refund-on-refile branch — rungs 33/34 reject every out-of-window and over-cap refile, so the calculation's refund variant is reachable only through abandon; reading it as dead vs. as a fallback path.
- FRICTION 8: §3.7 refile response body — the successor draft (201, my rendering) vs. the abandoned predecessor.
- FRICTION 9: §3.7 `filing_kind` vs. the parent obligation's `obligation_type` — nothing constrains them to agree; unconstrained vs. implicitly required to match.
- FRICTION 10: §3.8/§3.11 `reinstatement_case_id` is an accepted input with no persisted `Filing` field; case<->filing linkage by stored reference vs. by registration plus `REINSTATEMENT` kind.
- FRICTION 11: §3.9 acknowledging from `ESCALATED` — the derived definition of `sop_priority_hold` clears it, while only the `FORWARDED -> ACKNOWLEDGED` leg lists the clear as a side effect.
- FRICTION 12: §3.13 ops-run cascade depth within one run — whether step 4 sees step 1's results (so `ACTIVE -> DELINQUENT -> ADMIN_DISSOLVED` in a single sweep) or each run advances one hop.
- FRICTION 13: §3.3 the `RESIGNATION_NOTICED` leg of the registration-closure appointment sweep — reachable only when a closed notice window has not yet been retired by an ops-run; live branch vs. vestigial.

## Step 5: Generate unit tests — 2026-08-08T17:44:00.000Z

Test infrastructure and suite are complete and verified.

### What was built

**`test_helpers/`** (8 modules, ~1,400 lines) — `types.py` (24 enums + TypedDicts, with the three lean resource types omitting `updated_at`/`version`), `api_client.py` (75 endpoint methods, one per PRD §4 row), `api_errors.py` (40 error ids + status map registered with the framework), `assertions.py`, `factories.py` (jurisdiction-rule payloads reproduced verbatim from the design recipes), `constants.py`, `test_users.py`, `fixtures.py` (5 tiers of composite setup).

**`test_suite/`** — 21 files, **105 tests**, 0 skip/xfail.

### Coverage

- **Queue A (difficulty): 18/18 instances translated, 0 skipped**, 2 tests each = 36 tests.
- **Queue B (corner): 68/68 non-stub instances translated, 0 skipped**, 69 tests (the reinstatement pricing/grant instance carries 2). All 10 `excluded_because:` stubs verified to resolve to real difficulty instances and left untranslated.
- `Design:` tags = 105 = `def test_` count; every tag resolves to a real `name:` in its source yaml.
- **221 PRD citations machine-verified verbatim** against `PRD.md` (whitespace-normalised substring match) — 13 initial truncations were extended to full sentences and re-verified.

### Friction handling (all 13 checked; 0 tests depend on an un-adjudicated reading)

Agreement-by-construction derivations:
- **F3 (`registration_count`)** — `test_portfolio_summary_equals_the_sum_of_its_state_parts`: both registrations are `PENDING` and never closed, so "every status" = 2 and "occupied only" = 2.
- **F4 (BOI/final-report `due_date`)** — no test asserts `due_date` on a `BOI_INITIAL`/`BOI_UPDATE`/`FINAL_REPORT` row. Money still coincides: the DE rule's `late_fee_flat_cents` defaults to 0, so `late_fee_cents` = 0 under either due-date reading -> `total_due_cents` = 0+0+0+4900 = 4900. The `FINAL_REPORT` row is only asserted as `SCHEDULED` (no ops-run runs).
- **F6 (refile re-prices `late_fee_cents`)** — obligation due 2027-03-01, `grace_days` 0 -> `grace_end_date` 2027-03-01; refile at clock 2026-05-05, so days-late = max(0, 2026-05-05 - 2027-03-01) = 0 under both readings -> successor `state_fee_cents` = 5000 + 0 + 0 either way.
- **F10 (`reinstatement_case_id` linkage)** — exactly one case and one `REINSTATEMENT` filing on the registration, so "stored reference" and "registration + kind" select the same row.
- **F8 (refile response body)** — the successor is located through `GET /filings?compliance_obligation_id=...` rather than the refile response body; only HTTP 201 is asserted, which both readings return.
- **F1/F2 (clock source, list tie-break)** — no test asserts a `created_at`/`updated_at` value, and every `[0]` index is on a list whose `total_count == 1` (or a filtered singleton), so no relative order of tied rows is asserted. **F5, F7, F9, F11, F12, F13** are not touched by any emitted test (F12 in particular: every multi-hop expectation is a single ops-run step plus its own PRD-stated side effect, never a later step reading an earlier step's result).

### Other guarantees

- `assert_same_instant()` parses both sides into aware datetimes; used for all 14 timestamp assertions (`.000Z` vs `Z` vs offsets cannot cause a false failure). Ids asserted via `is_valid_uuid`, never against literals.
- All numeric literals carry hand-derivation comments (business-hour cursor walks, month-length clamps + forward rolls, assumed-par-value chains, `4901 x 4900/9800 = 2450.5 -> 2451` and its 2450 remainder, the 4900->4165 discount).
- Design-recipe inputs used verbatim; `pytest --collect-only` collects 105 tests; all 21 modules import cleanly; pyflakes reports no undefined names. Nothing under `workspace/implementation/` was read or created.

## Step 6: Generate implementation — 2026-08-08T17:44:00.000Z

Implementation complete at `workspace/implementation/`.

### Scale
**34 Python modules, 4,906 lines** + `start.sh` + `requirements.txt`. Layout: 12 core modules (`app`, `dispatch`, `validation`, `timeutil`, `store`, `serializers`, `envelope`, `errors`, `lookup`, `listing`, `money`, `constants`), 13 route modules, 9 service modules. Every module authored in bounded writes; `ast.parse` clean on all 34.

### Endpoint completeness gate
`ENDPOINT GATE: 75/75, MISSING 0, EXTRA 0` — scaffold `endpoints[]` enumerated programmatically, app booted in-process, `app.url_map` dumped, path params normalised on both sides. A second gate also verified **roles and success codes: 0 mismatches across all 75**.

### Kill/relaunch simulation
Two runs of a tight `kill -9` + relaunch loop (15 and 14 rounds) against the dying LISTEN socket: **29 rounds, 0 start failures**. `app.py` creates the socket itself with `SO_REUSEADDR`, binds in a 40x0.25 s EADDRINUSE-tolerant retry loop, then serves via `werkzeug.serving.make_server(..., threaded=True, fd=sock.fileno())` in the foreground. `app.run()` is not used.

### Timestamp adjudication (HTTP-verified)
One renderer (`timeutil.render_instant`) for every server-written instant. Form: **`YYYY-MM-DDTHH:MM:SS.mmmZ`** — three fractional digits always present, always `Z`. Caller-supplied instants are **normalised, never echoed verbatim**; dates (`YYYY-MM-DD`) are echoed verbatim and derived dates render as plain dates with no time component. `created_at`/`updated_at`/`api_request_timestamp` all read the logical clock.

```
in  {"to_iso8601":"2026-06-15T08:00:00Z"}
out {"current_utc":"2026-06-15T08:00:00.000Z","previous_utc":"2026-05-01T00:00:00.000Z"}
in  {"to_iso8601":"2026-06-15T12:34:56.789+02:00"}
out {"current_utc":"2026-06-15T10:34:56.789Z", ...}
then POST /clients -> "created_at":"2026-06-15T10:34:56.789Z","updated_at":"2026-06-15T10:34:56.789Z"
```

### Closed enum-routing list (rung 14 -> `ERR_INVALID_ENUM` 422)
`entity_type`, `boi_exempt_class`, `owner_status`, `annual_report_basis`, `franchise_tax_basis`, `grace_basis`, `late_fee_style`, `obligation_type`, `filing_kind`, `expedite_tier`, `sop_class`, `report_kind`, `result`, `outcome` (both record-outcome endpoints). **No other field routes here.**

Named exclusions -> `ERR_INVALID_REQUEST` 400 (rung 13): every numeric/boolean/date/id/state-code field; `rebuild_types` (PRD §3.6 says so explicitly); all free-text fields. Query-string filters are excluded entirely — an unrecognised filter value returns an empty page, never a 4xx. Membership checks are *deferred* until after all rung-13 checks so a rung-13 failure anywhere in the body always wins.

HTTP-verified both branches:
- `entity_type:"TRUST"` -> `ERR_INVALID_ENUM`, **HTTP 422**
- `home_state_code:"de"` -> `ERR_INVALID_REQUEST`, **HTTP 400**
- `?status=NOT_A_STATUS` -> **HTTP 200**, `total_count: 0`

### The 13 friction adjudications
Each is commented at its code site as `ADJUDICATION OF FRICTION N`.

1. **created_at/updated_at source** -> **logical clock** (§2.5's universal quantifier; makes every stamp caller-derivable).
2. **List tie-break** -> **insertion order** via a monotone `_seq` (PRD-explicit); ids ascend in creation order too, so both readings coincide.
3. **Portfolio summary** -> `registration_count` counts **every status**; `worst_state_code` on a tie picks the **first-created** registration at the max rank (deterministic => assertable).
4. **`due_date` for BOI/FINAL_REPORT obligations** -> **state-rule formula for every type** ("the type does not branch the formula"); keeps all three bases + grace/delinquency/reminder machinery reachable on all five types and avoids an undefined derivation when the federal deadline is null.
5. **Expedite state surcharge on an obligation-backed filing** -> **the obligation's pinned `governing_rule_id`** (rung 18 is declared *not* to apply to that endpoint, so it must never be able to raise `ERR_NO_EFFECTIVE_STATE_RULE`).
6. **Refile pricing** -> **reuse the predecessor's stored `state_fee_cents`**, re-deriving only the expedite halves under the same pinned rule; the obligation is not re-priced and its version does not move (no undeclared side effect on a version-less endpoint).
7. **Refund-on-refile** -> **dead path** (PRD says it outright); the refund machinery lives only on `/abandon`.
8. **Refile response body** -> **successor draft, HTTP 201**.
9. **`filing_kind` vs parent `obligation_type`** -> **unconstrained** (no rung, precondition or error id covers a mismatch).
10. **`reinstatement_case_id` linkage** -> **by registration + `REINSTATEMENT` kind** (as both declared cascades state their preconditions); the optional input is retained internally only to price the draft and disambiguate, so both cascades fire with or without it.
11. **`sop_priority_hold` on acknowledge from `ESCALATED`** -> **re-evaluated on both legs** (keeps the flag's own "true exactly while..." invariant true at every instant).
12. **Ops-run cascade depth** -> **multi-hop within one sweep**, seven declared steps each run exactly once in order (a step-1 delinquency is eligible for step 4's dissolution sweep on the same run).
13. **`RESIGNATION_NOTICED` leg of the closure sweep** -> **live** (PRD names the exact residue it bites on: a closed window the ops-run has not yet retired).

### No seeded data / no persistence
Storage is Python dicts only. Audited: **no `open()`, sqlite, pickle, json.dump, file writes, or `/tmp` cache anywhere**; **no `datetime.now`/`utcnow`/`time.time`/`date.today`** (the only `time.sleep` is in the bind-retry loop). Verified on a fresh boot: `/registrations`, `/compliance-obligations`, `/filings`, `/agent-appointments`, `/state-rules` all return `total_count: 0`, and every restart round in the kill loop re-created its client from scratch.

### Behavioural verification
Three smoke suites (~150 assertions) all pass: gate precedence for all nine declared blocks, the 42-rung ladder ordering (incl. rung 13 beating rung 14, rung 11 body refs beating rung 13, rung 23 before 24, rung 26 before 27, rung 28 before 29, rung 32 before 37, rung 38 before 39), all four franchise-tax bases, all three late-fee styles, both grace bases, the volume-discount threshold (4->4900, 5->4165), the four conservation invariants after capture/abandon, waterfall ordering by statutory deadline with standalone filings last, the full reinstatement cycle (open->assess->pay->file->grant), `FINAL_REPORT` surviving termination, the SOP business-hour cursor and 3-rung escalation ladder with its channels, the BOI axis including the "date_of_birth alone arms nothing" carve-out, calendar rebuild, and the ops-run's idempotence (second run at the same instant returns all-zero counters and mutates nothing).

### Orchestrator notes
- Isolation held: Step 5 reported it never read/created anything under `workspace/implementation/`; Step 6 reported it never read `test_suite/` or `test_helpers/`. Both were launched in one assistant message.
- Independent counts: 105 `def test_` == 105 `Design:` tags; 0 skip/xfail/skipif across `test_suite/` + `test_helpers/`; 34 impl `.py` modules.
- `workspace/sweep.sh` pre-staged for Step 7 (2 waves of 4 + SWEEP_DONE marker) — a second pipeline (task_0931) is live on this host, load avg 4.6.

## Step 7: Run tests and iterate — 2026-08-08T18:05:00.000Z

The suite is clean on the first sweep, and both mandatory audits confirm it is fairly clean rather than falsely clean. **No files were modified** — no tests deleted, no fixes applied to `test_suite/`, `test_helpers/`, or `implementation/`.

**Iterations run:** 1 diagnostic iteration (0 fix cycles). A second full 8-round sweep was run as confirmation — **16/16 rounds, 105/105 each**.

**Tests deleted:** none. **Fixes applied to `test_suite/` / `test_helpers/` / `implementation/`:** none — no test failed in any round, so the diagnostic protocol never reached STEP 1.

**Final counts:** sweep 1 — 8/8 rounds, 105/105; sweep 2 — 8/8 rounds, 105/105. Sweep-1 results preserved at `workspace/sweep1_results/`; sweep-2 results are the live `implementation/results.{1..8}.json`.

### (i) Mechanical reality checks — all green
- All 8 `results.N.json` parse, each with **105 individual test rows**, every row `status: passed`.
- Sorted test-name set is **byte-identical across all 8 rounds**, and identical again across the confirmation sweep's 8 rounds.
- `def test_` count in `test_suite/` = 105 = runner's collected count; row-name set equals source-name set exactly.
- 0 `skip` / `xfail` / `skipif` anywhere in `test_suite/` or `test_helpers/`.
- `grep implementation/` for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` -> **empty**. Storage is in-memory dicts (`store.py`), nothing seeded, every collection empty at boot.
- Each round log contains `Killed` **exactly once**, immediately after the first test name — the expected per-test-server swap, not a crash.
- Bonus structural checks: 75 `@endpoint` registrations == 75 scaffold endpoints; all 40 error assertions are **exact `error_id`** (no `one_of` relaxations, no HTTP-status downgrades); **221 PRD quotes** extracted from test docstrings, **all 221 verbatim in `PRD.md`** (0 misses).

### (ii) Friction cross-check — 13/13, no latent unfairness

| # | Friction | Verdict |
|---|---|---|
| 1 | `created_at`/`updated_at` source -> logical clock | **PRD-GROUNDED (not a friction)** — `PRD.md:100` names `created_at`/`updated_at` explicitly. No test asserts a `created_at`/`updated_at` *value* at all. |
| 2 | List tie-break -> insertion order | **CLEAN** — `PRD.md:84` states "insertion order" verbatim. Id-monotonicity re-derived empirically (5000 minted ids, `sorted(ids) == ids`), so `_seq` and `id` orderings are provably identical. Every order-sensitive assertion is single-row, pre-`sorted()`, set/`all()`-based, or `find_by_id`. |
| 3a | `registration_count` counts every status | **AGREEMENT-BY-CONSTRUCTION** — the sole assertion (`test_04:322`) has both registrations `PENDING`; both readings give 2. (`PRD.md:250` states "every status" verbatim anyway.) |
| 3b | `worst_state_code` tie-break | **CLEAN** — genuinely un-adjudicated, but the field is **never asserted** (only quoted in a docstring). |
| 4 | BOI/FINAL_REPORT `due_date` | **PRD-GROUNDED + AGREEMENT-BY-CONSTRUCTION** — `PRD.md:314` says "the type does not branch the formula". Only 2 such obligations exist; neither asserts a date, and the money coincides under both readings. |
| 5 | Expedite surcharge rule version | **CLEAN** — all 13 obligation-backed drafts use tier `NONE` (state half hard-zero), and no test publishes a second rule version between obligation and filing creation. |
| 6 | Refile reuses predecessor `state_fee_cents` | **AGREEMENT-BY-CONSTRUCTION** — clock moves 2026-05-01 -> 05-05, still 330 days short of `grace_end_date` 2027-03-31; both readings yield `state_fee_cents = 5000`. |
| 7 | Refund-on-refile is a dead path | **PRD-GROUNDED** — `PRD.md:402` states it verbatim, and the test's docstring quotes that sentence. |
| 8 | Refile returns successor, 201 | **PRD-GROUNDED** — stated verbatim twice (`PRD.md:402`, `:535`); the test asserts only the 201 and discards the body. |
| 9 | `filing_kind` vs `obligation_type` unconstrained | **CLEAN** — all 13 obligation-backed drafts pass `ANNUAL_REPORT` against an `ANNUAL_REPORT` obligation. A matching pair succeeds under both readings. |
| 10 | REINSTATEMENT -> case linkage | **AGREEMENT-BY-CONSTRUCTION** — both REINSTATEMENT filings pass `reinstatement_case_id` explicitly, and only one case exists on the registration. |
| 11 | `sop_priority_hold` on ack from `ESCALATED` | **CLEAN** — `acknowledge_sop_document` has **zero call sites**; all three `sop_priority_hold` assertions are on the *set* direction. Every `LITIGATION` document in the suite dies in `RECEIVED`. |
| 12 | Ops-run cascade depth | **AGREEMENT-BY-CONSTRUCTION** — the dissolution fixture uses **two** sweeps straddling `delinquency_date` 2027-05-30 (04-15, then 06-01), so step 4 never reads step 1's write. The only counter asserted anywhere is `obligations_advanced == 2`, a step-1 counter. |
| 13 | `RESIGNATION_NOTICED` closure leg live | **CLEAN** — `notice_resignation` has one call site (`test_02:164`), which retires via the ops-run and never closes the registration; the three closure sites have only plain `APPOINTED` appointments. |

### Near-miss register (thinnest margins first)
1. **`test_04:316-326` is one line from binding friction 3b.** DE and NY are tied at rank 0; adding `assert summary["worst_state_code"] == "DE"` would bind an un-adjudicated tie-break (last-created yields `"NY"`). Single most fragile point in the suite.
2. **`test_09:127-129` — the `reinstatement_case_id=case["id"]` kwarg is the entire margin for friction 10.** Deleting it makes `state_fee_cents == 65000` reading-dependent.
3. **`fixtures.py:369-378` — collapsing `setup_admin_dissolved_registration` to a single sweep** would make `ADMIN_DISSOLVED` depend on friction 12's multi-hop reading (cascading into 4 tests).
4. **`test_06:112` (friction 6)** is fair because the grace boundary sits ~330 days outside the 15-day refile window; a due-date edit placing `grace_end_date` between draft and refile would split the readings 5000 vs 25000.
5. **Any one of the 13 `draft_obligation_filing` kind literals (friction 9)** — a single token change to a non-matching kind flips CLEAN to DEPENDS, since the PRD is *silent* on the pairing.
6. **`test_04` fixture (friction 3a)** — all registrations are `PENDING`; driving one terminal, or calling `get_portfolio_summary` from `test_09`/`test_10`, splits the two readings.
7. **`test_01:232-254`** — three rule fixtures share `effective_from: 2026-01-01` (a three-way tie) under `limit=2`; fair only because no row identity is asserted.

**One cosmetic inaccuracy noted, deliberately not "fixed":** the docstring at `implementation/store.py:122-127` claims "The PRD makes `id` a load-bearing list tie-break" — the PRD actually says *insertion order* (`PRD.md:84`) and never mentions `id`. The **behaviour** is correct (and the two orderings are provably identical); only the comment overstates.

### Orchestrator independent verification
- All 16 `results.N.json` (8 live + 8 preserved) re-parsed independently: `passed=105 failed=0 total=105`, **105 rows each**, status set exactly `{'passed'}`, and the sorted test-name SHA1 is **identical across all 16** (`82cb906b`).
- `grep` of `implementation/` for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()|date.today` -> empty.
- 0 skip/xfail/skipif in `test_suite/` + `test_helpers/`.
- Exactly one `Killed` per round log (expected pre-boot swap).
- `find test_suite test_helpers workspace/implementation -newer results.1.json` -> empty: nothing was touched after the sweep.

## Step 8: Finalize PRD — SKIPPED — 2026-08-08T18:05:00.000Z

Step 7 exited on its first 8-round sweep with **0 deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 0 `implementation/` fixes**. Per the skip condition, `PRD.md` already determined every behavior the implementation exhibits at every site Step 7 touched, so no `PRD_FINALIZED.md` is produced. Step 9 therefore starts from `PRD.md` and carries the whole completeness burden.

## Step 9: Complete PRD — 2026-08-08T18:35:00.000Z

`PRD_COMPLETED.md` written from `PRD.md` (no `PRD_FINALIZED.md` — Step 8 skipped).

### Scale
- `PRD.md`: 662 lines / 143,479 chars -> `PRD_COMPLETED.md`: 674 lines / 182,807 chars (**+12 lines, +39,328 chars**)
- 81 `Edit` operations; 98 lines rewritten or added. **No new `#` headers** — both files carry the identical 34 headers in the identical order; the §4 endpoint table and §5 error table are byte-identical.
- **63 ambiguity-pins, 18 mismatch-revisions.**

### Changes

**§2.1–2.2** — insert — ambiguity — header values whitespace-trimmed before matching/recording (`dispatch.py:108`) · `api_request_id` = `req_` + exactly 20 uppercase-alnum (`envelope.py:19`) · `api_request_timestamp` read from the **logical clock**, not the host clock (`envelope.py:25`) · pagination keys appear on list responses only (`envelope.py:29`).

**§2.3** — insert/revise — ambiguity x5 — non-integer `limit`/`offset` -> `ERR_INVALID_REQUEST` (`dispatch.py:179`) · filters compare the raw query string for equality, so an unrecognised value returns an **empty page, never a 4xx** (`dispatch.py:196`) · `/state-rules` also accepts a `state_code` filter (`state_rules.py:120`) · rule ordering estate-wide descending with insertion-order tie-break (`state_rules.py:124`) · id minting makes insertion order and id order coincide (`store.py:29`).

**§2.3** — insert — **mismatch** — `GET /registrations`, `/compliance-obligations`, `/filings` **narrow** to the acting `ClientContact` instead of raising (`listing.py:26`, `obligations.py:93`, `filings.py:140`).

**§2.4** — insert — ambiguity x3 — explicit `null` == omitted; unknown body keys ignored (`validation.py:61`) · full instant/date rendering contract, caller instants **normalised not echoed** (`timeutil.py:35,57`) · the three internal bookkeeping values no response carries (`filings.py:48`, `reinstatement.py:60`).

**§2.4** — revise — **mismatch** — "version increases on every mutation" narrowed: rollup recomputation moves **no** `version`/`updated_at`; one request = one bump per row; an empty PATCH still bumps (`rollups.py:1-7,34`, `legal_entities.py:124`).

**§2.4** — insert — **mismatch** (Q1) — the enumerated list of ~28 declared fields **written and never read** by any gate, derivation or rollup, plus the two read only by their own bookkeeping.

**§2.5** — revise — ambiguity — `to_iso8601` accepted forms (`Z`/`z`/offset/naive/date-only); response is a bare `current_utc`/`previous_utc` object; sub-ms truncated (`clock_ops.py:13-25`).

**§2.6** — insert — ambiguity x2 — closing the incumbent bumps its `version`; rung 19 vacuous with no open row (`state_rules.py:65,106`) · a rule read returns every catalogue field with defaults filled and arrays normalised (`serializers.py:68`).

**§2.9 rung 11** — insert — ambiguity — body-reference resolution runs on **every** endpoint carrying one of the four keys; a non-string value fails identically (`dispatch.py:132-142`).

**§2.9 rung 12** — revise — **mismatch** — applies only to endpoints addressing a resource by `{id}`; the three estate-wide lists cannot fail it (`dispatch.py:145`).

**§2.9 rung 13** — insert — ambiguity — malformed/non-object JSON fails here but only after rungs 1–12; blank-string, bool-vs-int, date-format rules (`dispatch.py:162`, `validation.py:69-133`).

**§2.9 rung 14** — revise — **mismatch** — name-clearance `result` admits `PENDING`; membership deferred until every rung-13 check passes; non-string enum = rung 13 (`constants.py:128`, `validation.py:185-204`).

**§2.9 rung 20** — insert — ambiguity — the "new registration's start date" is the **current clock date** (`registrations.py:84,109`).

**§2.9 rungs 23/24/25/26** — insert — ambiguity x4 — rung 23 passes when no `HOME` registration exists · rung 24 checks only `issued_on` · rung 25 checks only `result`/`fallback` · rung 26 **skipped** when no rule is effective today (`registrations.py:111,125,128,32-41`).

**§2.9 rungs 30/40/42** — insert — ambiguity/mismatch — rung 30 requires status exactly `APPOINTED` · **mismatch:** rung 40 sits after rung 16 on the BOI draft · rung 42's per-endpoint source date, rung-16 precedence, rung 18 before rung 42 on assess (`registrations.py:176,330`, `boi_reports.py:26-29`, `reinstatement.py:22-26`).

**§2.10** — revise — **mismatch** — the parent/child scoping rule never fires: **no declared path carries two identifiers** (`dispatch.py:22-35`).

**§2.11** — revise — ambiguity (Q3) x2 — `delinquency_rank` is not a proxy for `status` in either direction (rank 3 on a `PENDING` registration; rank 4 forever after `CLOSED_PERMANENT`) · `sop_open_escalation_count` derived from events on open documents, recomputed wholesale (`rollups.py:21-31,50-61`).

**§2.12** — insert — **mismatch** (Q4) — hop 2 carries **no precondition on the obligation's status** (terminal rows re-terminated as `SATISFIED`); hop 3 reaches `SENT` notices too; hop 5 moves no version; every other hop bumps once per row (`filings.py:206-210`, `obligations.py:222-240,271`).

**§3.1** — insert/revise — ambiguity x4, mismatch x1 — portfolio summary: `registration_count` in every status, `worst_state_code` tie-break = earliest-created at max rank, bare eight-key projection (`clients.py:58-92`) · `issued_shares` ceiling is rung 13 · **mismatch:** an entity created already exempt is born `PENDING_INITIAL` with a null deadline, not `NOT_REQUIRED` (`legal_entities.py:53-54`) · PATCH change-detection, exempt-before-rename ordering, one bump per request · activation otherwise inert · `billing_email` unvalidated.

**§3.2** — insert — ambiguity x5 — `qualified_on`/`assumed_name`/`sop_priority_hold` consulted by nothing · home-registration gate order, unused resolved rule · `record-result` accepts `PENDING`, re-recording allowed, `conflicting_name` **recorded whatever the result and never cleared** (mismatch) · certificate `issued_on` may be future.

**§3.3** — insert — ambiguity x3 — proposing is ungated; `appointed_on` never compared to the clock · acceptance transfers out **every** `APPOINTED` sibling; the appointment list is not client-narrowed · the selector writes `of_record=false` on non-candidates and **moves no version**, which is why ops-run step 7 can flip `agent_of_record_id` silently (`agents.py:7-33`, `opsrun.py:113`).

**§3.4** — insert — ambiguity x3 — **the state-rule formula produces `due_date` for `BOI_INITIAL`/`BOI_UPDATE`/`FINAL_REPORT` too**; federal deadlines never consulted (`obligations.py:25-56`) · `rule_determination_date` read by nothing · a row already `DELINQUENT` is **never re-priced by a later ops-run**.

**§3.5** — insert/revise — ambiguity x1, mismatch x1 — franchise tax reads the entity's **current** figures under the pinned rule · **mismatch:** `waiver_reason` is required-but-blank-legal and **discarded**; waive zeroes only `total_due_cents`, suppresses `PENDING` **and** `SENT`, offers the cure hop (`obligations.py:116-124`).

**§3.6** — insert — ambiguity x3 — five notices minted 90/60/30/7/`OVERDUE`, which is their list order · a rebuild re-derives dates only — **no money field moves** · bare four-key response; re-arm touches `PENDING`/`SENT` only; obligation bumps only when `due_date` moved.

**§3.7** — insert/revise — ambiguity x6, mismatch x3 — obligation-backed draft: `filing_kind` **unconstrained** by `obligation_type`, `good_standing_certificate_id` rung-11-resolved then discarded, re-pricing + version bump **unconditional** · **mismatch:** standalone `good_standing_certificate_id` recorded whatever the kind · **mismatch:** "Five money fields" -> six · the **expedite surcharge comes from the obligation's pinned rule** · standalone `ANNUAL_REPORT`/`FRANCHISE_TAX`/`FINAL_REPORT` price at 0; unnamed reinstatement case = most recent **assessed** case · case linkage rule for both cascades · **mismatch:** `rejection_reason` written only on the rejection leg · refile **reuses the predecessor's stored `state_fee_cents`**, never touches the parent obligation · abandon: "the funding payment" = payment behind the **earliest forward allocation**, and **no reversal row at all** when the service sum is <= 0.

**§3.8** — insert — ambiguity x5 — `capture_amount_cents` of 0 is well formed · waterfall insertion-order tie-break; a named target skips re-testing · `paid_amount_cents` re-derived as a net sum; `sequence_index` zero-based **per capture** · the reinstatement hop examines only filings this capture funded · allocation listings take no filter.

**§3.9** — insert — ambiguity x5 — `plaintiff_name`/`court_case_number` never required, never read · pre-emption advances **from the deadline already carried** and bumps the sibling's version · `sop_priority_hold` re-evaluated on **both** acknowledgment legs, written only on change, gated on by nothing, never cleared by closure · scan re-evaluates on both legs · escalation rollups move no client version; `ack_deadline_at` re-armed from the escalation instant.

**§3.10** — insert/revise — ambiguity x3, mismatch x4 — **mismatch:** `is_company_applicant` not updatable and read by nothing; `date_of_birth` likewise; no constraint on summed `ownership_pct` · a re-sent identical value is **not** a reportable change · **mismatch:** claiming an exemption from a non-`PENDING_INITIAL` axis leaves the axis but **still nulls both deadlines** · **mismatch:** **any** accepted report drives the axis to `FILED` · a null deadline never goes `DELINQUENT` · **mismatch:** draft gate order 15->16->40; `deadline_date`/`triggering_change_date`/`owner_snapshot_count` read by nothing.

**§3.11** — insert/revise — ambiguity x4, mismatch x2 — `reinstatement_deadline` **fallback chain** when no rule is effective on `admin_dissolved_on` (latest-ever row, then 365) · opening a case: rung 16 first, duplicates allowed · assessment uses the row's stored `state_fee_cents` and the recomputed franchise tax as the `PERCENT_CAPPED` base · rung 18 before rung 42; **the assessment touches not one obligation** · **mismatch:** grant cures exactly the **remembered snapshot** and `reinstatement_deadline` is **not** cleared · **mismatch:** closure-expired cases are counted in `cases_expired`; the voided obligations counted nowhere.

**§3.12** — insert — ambiguity x2 — the closure appointment sweep bumps each appointment and the `RESIGNATION_NOTICED` leg is **live** · dissolve leaves both BOI deadlines and `final_report_required` standing, bumps once, writes the client rollup without a client version.

**§3.13** — revise — **mismatch** — step 7 restated to include the estate-wide agent-of-record re-derivation; the sweep is **multi-hop within one run** (step 1 -> step 4 on the same invocation) and bounded by the seven steps; never runs the cure hop; `cases_expired` aggregates both sources while step 7's flips and the closure's voids are counted by nothing.

**§5** — insert — ambiguity — an unrouted path answers `ERR_RECORD_NOT_FOUND`/404 and a wrong method answers `ERR_INVALID_REQUEST`/**400, not 405**; trailing slashes tolerated.

All 13 `ADJUDICATION OF FRICTION` sites were located, read against the surrounding code rather than trusted from the comment, and pinned. Two comment claims were narrowed against the code: friction 11's comment describes re-evaluation but the code additionally suppresses the write (and the version bump) when the flag does not change; friction 3's `worst_state_code` tie-break resolves to the **earliest-created** row at the maximum rank, not merely "deterministic".

### Orchestrator independent verification
- `diff` of all `^#` headers, `PRD.md` vs `PRD_COMPLETED.md`: **empty** — no sections added.
- Line/char counts confirmed: 662/143,479 -> 674/182,807.
- `find test_suite test_helpers workspace/implementation -newer results.1.json`: **empty** — Step 9 touched no code or tests, so the 16/16 green sweep still describes the shipped artifact.

## Pipeline complete — 2026-08-08T18:35:00.000Z

105/105 tests passing on 16/16 sweep rounds, 0 deletions, 0 fixes. Artifacts: SCAFFOLD.yaml + 2 design indices, PRD.md, PRD_COMPLETED.md, test_helpers/ (8 modules), test_suite/ (21 files / 105 tests), workspace/implementation/ (34 modules / 4,906 lines).
