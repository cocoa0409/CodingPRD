# Worklog — task_0931_virtual_address_cmra

Scenario (verbatim from user):
> 931. Virtual-Address & Mail-Scanning (CMRA): box/plan & Form 1583, mail receipt & scan/forward, package acceptance & notification, shredding & check-deposit, registered-agent add-on, plan tier & overage, USPS compliance & ID, cancellation

Difficulty: **beyond-Expert** (user asked "generate task hard than expert level!").

## Step 1: Create task directory — 2026-08-08T15:59:40.000Z

Created `tasks/task_0931_virtual_address_cmra/workspace/` (index 0931, next after 0930).

## Step 3: Copy shared files — 2026-08-08T15:59:40.000Z

Copied `INSTRUCTION.md` → `tasks/task_0931_virtual_address_cmra/workspace/INSTRUCTION.md` (done early, alongside Step 1; no dependency on Step 2).

## Step 2: Generate scaffold — 2026-08-08T16:48:00.000Z

All three files are written and verified. Final report:

## Files produced (all in `/home/ubuntu/github/CodingPRD/tasks/task_0931_virtual_address_cmra/`)
- `SCAFFOLD.yaml` (3779 lines) — §1.0–§1.7 plus `constants`, `gate_precedence`, `conservation_invariants`, `concurrency_rules`
- `SCAFFOLD_DIFFICULTY_DESIGN.yaml` (2338 lines) — single key `scaffold_difficulty_design`
- `SCAFFOLD_CORNER_DESIGN.yaml` (3454 lines) — single key `scaffold_corner_design`

## Metrics
| Dimension | Value | Target |
|---|---|---|
| Entities | 17 | 15–18 |
| Endpoints | 74 | 62–75 |
| SM axes | 16 (13 non-linear: 4 cyclic-and-branching, 1 pure cyclic, 8 branching-with-divergent-side-effects; 3 parallel axes on MailItem, 2 on Box, 2 on Recipient) | 10–14 / ≥8 non-linear |
| Calculations | 25, of which **7 dual-variant** | 18–24 / ≥6 |
| Error codes | 42 | 32–40 (slight overshoot: 14 are per-resource 404s, all triggerable) |
| Ladder rungs | 36 | 34–42 |
| OCC rules | 4 | 2–4 |
| Conservation invariants | 5 | 3–5 |
| Max cascade depth | **7 hops** (ComplianceReview → Box → DispositionRequest → MailItem.handling → MailItem.storage → UsageLedgerEntry/BillingCycle → Recipient → MailItem) | ≥5 |
| Declared constants | **47, 0 undeclared** | — |
| §1.8 instances | 23 (9 rules × 2–3) | ≥18 |
| §1.9 instances | 67 (58 with recipes, 9 `excluded_because` stubs) across all 9 guide sections | — |

`scaffold_lint.py` → **VERDICT: clean lint** (1126 calls scanned, all FKs reverse-reachable). All 3 files pass `yaml.safe_load`. All 90 instance names unique; a custom grounds-resolver confirmed **0 dangling grounds refs**. No banned concurrency vocabulary.

## Self-repairs from the reachability audit (D)
1. **C3 was dead code.** `ERR_ID_DOCUMENT_EXPIRED` (rung 19) was unreachable because C2 was written over `status == VERIFIED`: an expiring document removed itself from C2 first, so C3 could never fail. Introduced `governing(D)` = latest-`verified_at` doc of class D with status ∈ {VERIFIED, EXPIRED}; C2 now fails only on *never verified*, C3 on *verified-then-expired*.
2. **Double-counted storage allowance.** `overage_metering` would have re-applied `included_storage_days` at cycle level after `storage_days` had already subtracted the per-item free window. Pinned `included(STORAGE_DAY) = 0` with an explicit rationale; the quota invariant was restated accordingly.
3. **`blocked_reason` had no value for roster suspension** — C5 collided onto `NO_ACCEPTED_1583`. Added `ROSTER_NOT_AUTHORIZED`.
4. **Contradictory notification writer.** `AWAITING_CLEARANCE → HELD` and `package-acceptance` both set `notification_status`. Ownership given solely to `package-acceptance`; the clearance hop now re-evaluates the storage axis instead (which is what makes the depth-5 form-1583 cascade real).
5. **`billable_weight_lb` undefined for LETTER/FLAT**, yet the forward weight bracket reads it. Now set at intake to `actual_weight_lb` for every piece and recomputed at acceptance for PACKAGE/SOP.
6. **Minor's guarantor never re-derived.** Accepting the guarantor's Form 1583 didn't propagate; added an explicit dependents re-derivation so `GUARANTOR_BLOCKED → RELEASABLE` is reachable.
7. **Batch close was unreachable** — `CheckDeposit MATCHED → DEPOSITED` required the MailItem to be in `PENDING_DISPOSITION`, which blocked ordinary deposits. Relaxed to a conditional side effect; the item transition now additionally requires a PENDING DEPOSIT request.
8. **Dead enum values removed**: `CheckDeposit.BATCHED`, `CheckDeposit.hold_reason CAP_EXCEEDED`, `CancellationRequest.NOTICE_PERIOD`, `ForwardShipment.DRAFT` — none had a producing transition.
9. **`carrier_rule_id` was forbidden for SOP**, contradicting SOP pricing/oversize paths; now required for `{PACKAGE, SOP}`.
10. **Cascade ordering was unpinned** (recipient-suspension vs. disposition-cancellation raced to decide the item's final `handling_status`). The 7 hops are now pinned in a fixed order on `ComplianceReview.OPEN_to_SUSPENDED`.
11. **YAML lint fixes**: PyYAML rejects `?` in flow-sequence plain scalars and `[` inside flow collections — all `field?` inputs, all `$.data[N]…` captures, and all `grounds:` entries are quoted.

## Domain-seam coverage (E) — all 12 exercised
1583 as global write gate with monotone time-derived ID expiry (gate C1/C2/C3, rungs 17–19) · roster-vs-box with USPS cap, minor guarantors and a distinct refuse/RTS path · three parallel MailItem axes with cross-axis gating · three scan tiers with separate quota math, consent, OCR multiplier and a 25-page split cap · four competing terminal dispositions with a precedence table, supersede-vs-conflict branches and OCC · carrier-specific acceptance with dim-vs-actual dual-variant pricing, oversize refusal, signature authorization and an SLA clock · check deposit with normalized exact/DBA-alias matching, endorsement, cutoff hour, per-check/per-batch caps and a money-partition invariant · registered-agent SOP carve-outs (4h SLA, free acceptance, quota bypass, storage exemption, statutory retention that survives cancellation) · plan tiers with waterfall overage metering, load-bearing proration rounding order and deferred downgrades · free-window-then-accrual storage plus weight-bracket × service-level forwarding with partial consolidation · compliance suspension as a second global gate with an explicit machine-checkable `gate_precedence` block · cancellation with notice/final-forward/abandonment/retention dates and a conserving refund waterfall.

## Boundaries (F)
Every window/threshold states its edge explicitly: oversize `>` (strict), storage `>` (strict), scan split `<=`, forward brackets inclusive upper bound, consolidation `>=`, loyalty tiers `>=`, roster cap `>=`, deposit cutoff `>=` (half-open window), check amount `>` (strict), retention floor `>=` (finalizing *on* the date is allowed), ID expiry `>` (strict), notification breach `>` (strict).

**Orchestrator verification:** all 3 files `yaml.safe_load` clean; independent count → 17 entities, 74 endpoints; independent ALL_CAPS constant-shaped sweep → 47 declared, 1 residual token (`FREE_WINDOW`) confirmed to be a `storage_status` enum member, **0 undeclared**.

## Step 4: Generate PRD — 2026-08-08T17:04:00.000Z

The PRD is complete and all three hard contracts pass mechanically.

**Output:** `workspace/PRD.md` — 589 lines, 16,753 words. Structure: §1 Introduction, §2 with 11 subsections (2.2 emitted byte-verbatim from the fixed source, diff-confirmed), §3 with 13 workflow subsections, §4 endpoint table (4 columns), §5 error table (2 columns). No audit footer.

### Hard Contract Reports

```
Field coverage check:
- entities[].fields: 165 required, 165 present, 0 missing
- endpoints[].request_body/input: 69 required, 69 present, 0 missing
- endpoints[].query_params: 25 required, 25 present, 0 missing
Status: PASS
```
```
Rule coverage check:
- validations[] with priority: 36 checked, 36 expressed in prose (rung-by-rung, numeric order, each with error_id + HTTP status + applies_to scope), 0 missing
- concurrency_rules[] OCC rejections: 4 checked, 4 expressed (write_endpoint + expected_<parent>_version + ERR_STALE_VERSION + 412 all named), 0 missing
- state_machines[].transitions: 72 checked across 16 axes, 72 fully expressed, 0 missing
- calculations[]: 25 checked, 25 fully expressed (incl. all 7 dual-variant branches with equal density), 0 missing
- validations[] conditions: 36 checked, 36 matchable to error_id in prose, 0 missing
- endpoints[].side_effects / applies_to: 74 checked, 74 expressed, 0 missing
- entities[].fields[] structured content: 17 entities checked, all reconstructible (defaults, enum member sets, constraints, common_fields:false exclusions), 0 missing
- sibling-branch symmetry: 11 groups checked (3 removal edges, 2 match branches, 2 weight variants, 2 payee variants, 2 plan-change variants, 2 storage variants, 2 SLA variants, 2 retention variants, 2 fail branches, 5 forward brackets, 3 loyalty tiers), 0 asymmetric
Status: PASS
```
```
Path purity check (§3 only):
- backtick tokens scanned: 1222
- tokens starting with `/`: 0
- bare HTTP-method tokens: 0
- method+path combined tokens: 0
Status: PASS
```

### Beyond-Expert self-audit (H)

- **(i) Endpoints: 74/74.** Every scaffold endpoint appears in §4 with method, path, description and role list; request shape, response shape and error conditions are carried in §2/§3 narrative.
- **(ii) Error codes: 42/42** appear in PRD prose with triggering conditions (in §2.8/§2.9 ladder and §3 workflow sites), plus §5's ID+status table.
- **(iii) Constants: 47/47** appear with values. Eight are rendered in human form rather than raw digits and were individually verified: 1825→"1,825 days", 0.15→"15 percent", 7200→"7,200 cents", 1095→"1,095 days", 0.05→"5 percent", 0.10→"10 percent", `MONEY_ROUNDING`→§2.6, `PAYEE_NORMALIZATION`→§3.4 (spelled out character-by-character).
- **(iv) Transitions: 72/72** across all 16 axes, each with `from`/`to`, full precondition list and full side-effect list. All 54 distinct state values also appear as standalone backticked tokens.

Gate precedence (B) is rendered in §2.8 as three named gates with explicit blocked/exempt operation tables and the SOP carve-out; the ladder is §2.9, 36 numbered rungs in order. The 7-hop cascade (C) is written **once only**, hop-by-hop in §3.11, each hop with its non-firing condition — §2 deliberately carries no competing summary, eliminating the drift failure mode. Version ledger (E) is §2.4; timestamp rendering (F) is §2.4 (server instants always 3 fractional digits + `Z` regardless of the clock-setting string's format; caller-supplied `YYYY-MM-DD` dates echoed byte-for-byte).

### Un-adjudicated friction points (D) — 7, all rendered neutrally

1. **Gate C on box-level operations** (§2.8). Gate C is phrased over "the matched Recipient", but forward-shipment creation names an array of pieces with possibly different members, and check-logging resolves its member by payee matching inside the same request. Reading A: the gate is evaluated over every referenced member (or any one). Reading B: it does not apply to these two, since consolidation-eligibility already drops non-`RELEASABLE` pieces and payee mismatch routes to `HELD` rather than an error.
2. **Rung 7's error identifier** (§2.9). Rung 7 is declared with `ERR_RECIPIENT_NOT_FOUND` but its check covers body `mail_item_id` and every `mail_item_ids` member; separately `ERR_MAIL_ITEM_NOT_FOUND` is catalogued as covering "a mail item id in the path **or body**". Reading A: the rung's declared id wins. Reading B: the resource-typed id wins, as at rung 3.
3. **OCR multiplier in the ledger** (§3.6). `ScanJob.charge_cents` = overage pages × plan rate × tier multiplier; a ledger entry's `amount_cents` = `quantity` × `unit_rate_cents` where `unit_rate_cents` is "the overage rate". Reading A: multiplier folded into `unit_rate_cents`, so the cycle's `overage_total_cents` includes it. Reading B: multiplier lives only on `charge_cents` and the ledger carries the bare plan rate.
4. **Superseding disposition on an item already in `PENDING_DISPOSITION`** (§3.7). The custody axis declares only `HELD → PENDING_DISPOSITION` and no self-edge, yet `disposition_precedence` describes superseding requests that are already `PENDING` — reachable only from `PENDING_DISPOSITION`. Reading A: admitted by the precedence rule. Reading B: refused at rung 14 with `ERR_INVALID_STATE`.
5. **Multiple registered-agent add-ons per box** (§3.10). The collection is created and listed per mailbox with an `active` filter, implying several rows; every consuming rule says "the add-on", singular. Reading A: at most one active add-on is intended. Reading B: several may be active and some selection rule (most recent, first) governs `jurisdiction_code`/`retention_days`.
6. **RECIPIENT tranche rule** (§3.12). The roster transition tranches on the live post-transition `AUTHORIZED` count against `included_recipients + extra_recipient_slots`; overage metering tranches on the cycle's `recipients_consumed` against the same allowance. They diverge for a member authorized in a later cycle. Reading A: live-roster rule. Reading B: cycle-scoped rule.
7. **Billing-cycle `version` on close** (§3.12) — *scaffold-internal contradiction carried forward.* §2.4's ledger rule is one bump per row per request, but the scaffold declares a `version` increment on each of `OPEN → CLOSING` and `CLOSING → CLOSED`, both of which run inside a single request against the same row. Reading A: the closing cycle's `version` advances by 1. Reading B: by 2.

Other scaffold tensions judged **determined** (and therefore adjudicated in prose rather than flagged): Gate A exempts `POST /boxes/{id}/cancellation` while the `ACTIVE → CLOSING` transition requires `ACTIVE`, so a suspended box still fails at rung 14 — the exemption is inert but the outcome is fixed; `effective_gate_state`'s "priorities 11 and 12" and `gate_precedence`'s "11 and 17" describe different gates rather than conflicting, and are rendered as Gates A/B/C.

## Step 5: Generate unit tests — 2026-08-08T17:40:00.000Z

(Launched concurrently with Step 6 in a single assistant message.)

Test infrastructure and suite are complete.

### What was generated

**`test_helpers/`** (9 files, ~2.1k lines) — `types.py` (33 enums + 17 entity TypedDicts, `common_fields:false` respected for PlanTier/CarrierRule/UsageLedgerEntry), `api_client.py` (one method per PRD §4 endpoint), `api_errors.py` (42 ids + status map), `assertions.py` (per-entity asserts, the five §2.11 conservation checkers, and the semantic `parse_instant`/`assert_same_instant`), `factories.py`, `constants.py`, `test_users.py` (opaque-role constants + per-instance builders for the two `entity_backed` roles), `fixtures.py` (three tiers, headed by `setup_releasable_box`).

**`test_suite/`** — `conftest.py` + 15 domain-named test files.

### Self-audit (F)

- **Total tests emitted: 105.** `def test_` count = 105; `Design:` tag count = 105 (exactly one per test, every tag resolving to a real instance).
- **Queue A: 23/23 non-stub instances translated**, each with ≥2 tests (the seven-hop cascade got 3).
- **Queue B: 58/58 non-stub instances translated**, ≥1 test each. The 9 `excluded_because:` stubs were not translated; all 9 cross-references resolve to real difficulty instances (verified programmatically).
- **Instances SKIPPED: none.** No PRD-silence or unique-derivability collapse forced a skip; the two exposed friction points were neutralised in-place (below) rather than dropped.
- **0 occurrences** of `skip` / `skipif` / `xfail` / `pytest.skip`.
- **220 PRD citations checked verbatim** against `PRD.md` (whitespace-normalised substring match) — all pass. Every asserted response-field name appears verbatim in `PRD.md` (178 distinct names checked; the only non-matches were local fixture-context keys, not response fields).
- Suite collects cleanly under pytest (105 collected); pyflakes clean; no duplicate test names; no "scaffold"/table references in generated code.

### Friction-point disposition (A)

1. **Gate C on box-level operations — AGREEMENT-BY-CONSTRUCTION.** The only exposed case is `form_1583_safety_rung_preempts_deposit_cap_fiscal_rung`. The blocked-member cheque is logged at **600 000 cents against the 500 000-cent per-cheque cap**, so *both* readings refuse it and write nothing; the test asserts only `status_code >= 400`, `error_id ∈ {ERR_FORM_1583_INCOMPLETE, ERR_DEPOSIT_CAP_EXCEEDED}`, `check_count == 0`, `received_amount_cents == 0`. The companion test runs the identical cheque after acceptance (member `RELEASABLE`, so Gate C passes under either reading) and asserts `ERR_DEPOSIT_CAP_EXCEEDED` strictly. Every other forward-shipment / cheque test uses a `RELEASABLE` member.
2. **Rung 7's error identifier — AVOIDED.** No test supplies an unresolvable body `mail_item_id` or `mail_item_ids` member.
3. **OCR multiplier in the ledger — AGREEMENT-BY-CONSTRUCTION.** Every ledger/`overage_total_cents` assertion uses **`INTERIOR` (multiplier 1)**: the straddling request charges `10 × 25 × 1 = 250` and the ledger sums to 250; the loyalty close uses 100 `INTERIOR` pages → `overage_total_cents 2500` under both readings. The single `OCR` request in the suite is rejected at rung 21 and meters nothing.
4. **Superseding disposition on a `PENDING_DISPOSITION` item — AGREEMENT-BY-CONSTRUCTION for the refusal, AVOIDED for the supersession.** The `DEPOSIT`-over-`SHRED` supersession (201 vs `ERR_INVALID_STATE`) is not asserted at all. The two equal-rank collisions assert only what both readings share: **HTTP 409, `error_id ∈ {ERR_DISPOSITION_CONFLICT, ERR_INVALID_STATE}`, `total_count == 1` disposition, item still `PENDING_DISPOSITION`**. `precedence_rank` 4/1 is asserted only on *first* requests lodged from `HELD`, where no ambiguity exists.
5. **Multiple registered-agent add-ons — AVOIDED.** Every test attaches at most one add-on per mailbox.
6. **RECIPIENT tranche rule — AGREEMENT-BY-CONSTRUCTION.** Both RECIPIENT-ledger assertions sit in **cycle 1 with `included_recipients + extra_recipient_slots = 3 + 0 = 3`, live `AUTHORIZED` roster count = 1 and `recipients_consumed` before the event = 0**, so `min(1,·)` and `min(0,·)` both fall inside the allowance → `IN_TIER`, `unit_rate_cents 0`, `amount_cents 0` under either rule.
7. **Billing-cycle `version` on close — AVOIDED.** No test asserts a `BillingCycle.version` anywhere (verified by grep).

### Two additional adjudications worth recording

- **`ERR_CANCELLATION_ALREADY_PENDING` (rung 33) vs rung 14** and **`ERR_SCAN_RETRY_EXHAUSTED` (rung 28) vs rung 14** were both kept strict: §3.13 assigns `ERR_CANCELLATION_ALREADY_PENDING` to the not-`ACTIVE` clause explicitly ("failing which…"), and §3.6 states flatly "Retrying a job that has been abandoned is `ERR_SCAN_RETRY_EXHAUSTED`."
- **`assert_cancellation_request` deliberately does not check the refund-waterfall conservation**: §2.11 asserts it "after every request" while §3.13 says the three outputs "all start at 0" — a PRD self-contradiction on a `REQUESTED` row with a non-zero pool. Conservation is asserted only on the finalized row.

## Step 6: Generate implementation — 2026-08-08T17:37:00.000Z

(Launched concurrently with Step 5 in a single assistant message.)

Implementation complete at `workspace/implementation/`.

### Modules / line counts (3,637 lines total, 15 Python modules + `start.sh` + `requirements.txt`)
`app.py` 103 · `util.py` 275 · `errors.py` 119 · `store.py` 192 · `response.py` 63 · `calc.py` 139 · `domain.py` 352 · `serializers.py` 303 · `ladder.py` 351 · `routes_catalogue.py` 238 · `routes_roster.py` 298 · `routes_mail.py` 334 · `routes_disposition.py` 277 · `routes_checks.py` 191 · `routes_admin.py` 388 · `start.sh` 13.

### A — Endpoint completeness gate
Enumerated `SCAFFOLD.yaml endpoints[]` (74), booted the app in-process, dumped `app.url_map`, normalized `{id}`/`<ident>` to `{}`, diffed both directions:

**`N=74/74, MISSING 0, EXTRA 0`** (re-run after every subsequent edit, still clean).

### B — The two named bugs, adjudicated

**B1. Timestamp rendering — ONE producer.** Every rendered instant in the service goes through `util.render_instant()`; no other module formats a datetime (`grep` confirms `strftime`/`isoformat` appear nowhere else). It emits exactly three fractional digits + `Z`, unconditionally, truncating sub-millisecond precision. Caller-supplied *calendar dates* (`expires_on`, `business_date`) are stored as the raw string and echoed byte-for-byte; server-computed dates render as plain `YYYY-MM-DD`. **Observed wire bytes** (real HTTP, from `verify_b.py`):

| clock set with | server-minted `created_at`/`updated_at` on the wire |
|---|---|
| `2026-06-15T08:00:00.123456Z` | `2026-06-15T08:00:00.123Z` |
| `2026-06-15T10:30:00+02:00` | `2026-06-15T08:30:00.000Z` |
| `2026-06-16T09:00:00Z` | `2026-06-16T09:00:00.000Z` |
| envelope `api_request_timestamp` (same producer, logical clock) | `2026-06-16T09:00:00.000Z` |
| echoed caller-supplied `expires_on: "2026-12-31"` | `2026-12-31` (verbatim, not re-rendered) |

Nullable instants render as JSON `null`, verified.

**B2. Enum error routing — exhaustive closed list.** These and only these fields route to `ERR_INVALID_ENUM` (400) at rung 10:

*Body fields (13):* `tier_code` (POST /plan-tiers), `carrier_code` (POST /carrier-rules), `recipient_kind`, `rejection_reason`, `doc_class`, `doc_type`, `item_class`, `refusal_reason`, `scan_tier`, `disposition_type`, `service_level`, `reason` (review open), `resolution` (review resolve — accepted member set is `{CLEARED, ESCALATED_CLOSURE}` per §3.11, `NONE` is not a body-supplied member).
*Query filters (10):* `handling_status`, `storage_status`, `roster_status`, `release_eligibility`, `status` (member set per collection), `unit_type`, `tranche`, `doc_class`, `item_class`, `service_status`.

**No other field routes to `ERR_INVALID_ENUM`.** Named deliberate exclusions: `jurisdiction_code` (constrained *string*, two uppercase letters → `ERR_VALIDATION`); `signature_authorization_on_file`, `endorsed`, `signature_required`, `interior_scan_consent`, `allows_overage`, `accepts_signature_required` (booleans → `ERR_VALIDATION`); `to_iso8601`, `business_date`, `expires_on` (formatted strings → `ERR_VALIDATION`); `?tier_code`, `?carrier_code`, `?scan_tier` as **query filters** (rung 10's parenthetical enumerates the enum-valued query filters and these three are absent, while `doc_class`/`item_class` are present — so the enumeration is meant as closed; an unmatched value simply filters to empty); `?active` (boolean → `ERR_VALIDATION`); all system-computed enums (`suspended_reason`, `hold_reason`, `match_mode`, `blocked_reason`, `source_event`, …) are never body-supplied. **HTTP-verified:** `item_class="PARCEL"` → `ERR_INVALID_ENUM`; `?handling_status=NOPE` → `ERR_INVALID_ENUM`; exclusions `jurisdiction_code="xx"` → `ERR_VALIDATION` and `signature_authorization_on_file="MAYBE"` → `ERR_VALIDATION`. Also verified rung 9 pre-empts rung 10 (missing required field + bad enum → `ERR_VALIDATION`).

### C — EADDRINUSE-safe startup, simulated
`app.py` creates the socket itself with `SO_REUSEADDR`, binds inside a 40-attempt/0.25 s EADDRINUSE-tolerant loop, then serves via `werkzeug.serving.make_server(..., fd=sock.fileno())`; `start.sh` guards the pip install and `exec`s the server. Simulation: **15 tight kill/immediate-relaunch cycles (no grace period) → 0 start failures**, plus a later 12-cycle run → 0 failures. Each cycle also asserted the store came up empty.

### D — Deterministic ids
Ids are UUID-shaped but **monotonic**: a per-process counter occupies the first 12 hex digits (`%08x-%04x-4000-8000-%012x`), so ascending `id` string order equals creation order and the `created_at`-tie-break-by-`id` list ordering is deterministic under the coarse logical clock. **This is not seeded data** — the counter starts at 0 on every boot and mints ids only for rows the API is asked to create. Verified: `GET /mail-items` id sequence is already sorted.

### E — The 7 friction adjudications (each carries a `# Adjudication of friction N:` comment at its site)
1. **Gate C on box-level ops — Reading A.** Gate C *does* apply to both; for check-logging it is evaluated over the member payee matching resolves (skipped when none resolves, keeping the `PAYEE_MISMATCH` hold reachable); for forward-shipment creation it blocks only when *no* referenced member is `RELEASABLE`. Reading B would kill both rows of Gate C's blocked table; blocking on *any* blocked member would make the per-item eligibility clause "matched member is RELEASABLE" unreachable (rung 17 always pre-empts rung 32).
2. **Rung 7's error identifier — Reading B (`ERR_MAIL_ITEM_NOT_FOUND`).** Its catalogued condition covers "a mail item id in the path **or body**"; Reading A leaves that clause unreachable, while `ERR_RECIPIENT_NOT_FOUND` stays reachable either way via path ids and body `recipient_id`/`guarantor_recipient_id`.
3. **OCR multiplier in the ledger — Reading B.** Multiplier lives only on `ScanJob.charge_cents`; the ledger keeps `unit_rate_cents == the tier's overage rate`. Reading A would make that declared ledger formula unobservable for OCR.
4. **Superseding onto `PENDING_DISPOSITION` — Reading A (admitted).** Reading B would render `SUPERSEDED`, `LOST_PRECEDENCE` and the entire precedence contest unreachable, since superseding can only arise once the piece is already in `PENDING_DISPOSITION`.
5. **Multiple registered-agent add-ons — Reading B.** Several may be active; the governing one is the most recently created active add-on (`store.active_ra`), and `deactivate` targets it. Reading A would need an undeclared error for a second attach and would make the `active` list filter pointless.
6. **RECIPIENT tranche — Reading B (cycle `recipients_consumed`).** Reading A breaks the declared `quota_tranche_partition` invariant for any member authorized in a later cycle and would desynchronize rung 36 from every other consumption event.
7. **Billing-cycle `version` on close — Reading A (+1).** §2.4's "exactly once per row per request, never once per side effect" is a declared global rule; Reading B violates it and nothing becomes unreachable under A. (Enforced structurally: every mutation routes through `response.touch()`, which bumps a given row at most once per request.)

### F — No seeded data, in-memory only
`grep -rnE "sqlite|json\.dump|pickle|/tmp|open\("` over the implementation returns **one match: the `store.py` docstring sentence "no sqlite, no file"**. No other hit. Storage is plain Python dicts in `store.Store`; nothing is seeded, preloaded or hardcoded at import or boot, and the 12/15-cycle restart simulation asserted an empty store on every fresh boot.

### Additional verification performed
Three HTTP suites, all passing against a live server: a 60-assertion end-to-end smoke; a pricing/dates suite (dim weight `ceil(960/139)=7`, fee 685, 24 h vs 4 h SOP SLA, strict oversize boundaries, pinned per-item forward rounding `3×2538=7614` with 15 % discount `1142`, proration `round(6100×11/30)=2237` vs `round(12000×11/30)=4400`, cancellation dates `2026-05-02 → 06-01 / 06-16 / 06-26 / 07-26`, payee exact-vs-alias matching, deposit caps and the strict 21:00 cutoff); and a gates/cascades suite (Gate C rungs 17/18/19 individually, re-entrant `HELD ↔ AWAITING_CLEARANCE`, storage boundary at exactly `included_storage_days`, storage suspension under `PENDING_DISPOSITION` and resumption on withdrawal, the 7-hop suspension cascade, `ERR_QUOTA_EXHAUSTED` writing nothing, the SOP Gate-A carve-out excluding OCR, statutory retention, partial consolidation with `excluded_item_count`, holder/recipient scope, pagination bounds, and escalated-closure forfeiture).

**Isolation note (orchestrator):** Step 6 finished ~3 min before Step 5, so `implementation/` was on disk while test-gen finished. Both agents carried explicit containment instructions.

## Step 7: Run tests and iterate — 2026-08-08T18:15:00.000Z

All 105 tests pass across two consecutive 8-round sweeps (1,680 test executions, 0 failed, 0 errors). Route count still 74/74.

### Baseline sweep (round 1): 2 failure families

**1. One deterministic logic failure (8/8 rounds)** — `test_giving_notice_computes_the_four_closure_dates_and_locks_the_mailbox`: expected `ERR_CANCELLATION_ALREADY_PENDING`, got `ERR_INVALID_STATE`.

Root cause: the implementation evaluated the ladder in literal ascending order, so rung 14 (declared transition — the box must be `ACTIVE` for `ACTIVE → CLOSING`) pre-empted rung 33 (single pending cancellation). But **rung 33 is unreachable behind rung 14**: a cancellation in `REQUESTED`/`FINAL_FORWARD` always implies the mailbox is `CLOSING` (lodging drives `ACTIVE → CLOSING`, and only a withdrawal returns it to `ACTIVE` — which simultaneously retires the request). So `ERR_CANCELLATION_ALREADY_PENDING` could never be produced by any input.

Adjudication: PRD §3.13 attaches the identifier to the pending-cancellation clause explicitly ("…may already sit in `REQUESTED` or `FINAL_FORWARD`, failing which the request is `ERR_CANCELLATION_ALREADY_PENDING`"), and `SCAFFOLD_DIFFICULTY_DESIGN.yaml`'s instance `cancellation_occupies_the_box_until_withdrawn` asserts flatly "the second trigger call returns 409 with error_id ERR_CANCELLATION_ALREADY_PENDING". The test is right; the impl was wrong.

Fix — `workspace/implementation/routes_admin.py`, `create_cancellation`: rung 33's check now runs ahead of rung 14's, **only on this endpoint**, with a comment recording the reachability argument. Rung 14 still fires for every other non-`ACTIVE` `service_status` (`SUSPENDED`, and `CLOSING` with no live request), so neither rung is dead.

**2. Eight "could not be restarted" setup errors + one `RemoteDisconnected`**, scattered across `test_03/04/05/06/08` — ~1% of 840 per-test reboots, one per round. Not a logic bug: a slow-boot/EADDRINUSE flake under the 4-way concurrent sweep.

Diagnosis: 800 restarts under 4-way concurrency in isolation reproduced nothing, so I instrumented boot phases and captured the server's stderr (normally sent to `DEVNULL` by the harness's `_restart_server`). Measurements showed `start.sh`'s dependency probe `python3 -c "import flask"` cost **~265 ms of pure interpreter work on every reboot** — roughly doubling boot cost — and `_bind`'s retry loop (40 × 0.25 s) would give up at 10 s, inside the harness's 15 s poll budget, while sleeping through most of it.

Fixes:
- `start.sh`: probe with `importlib.util.find_spec('flask')` instead of importing flask (265 ms → 19 ms).
- `app.py` `_bind`: 40 × 0.25 s → 300 × 0.05 s, so a genuinely-held port is retaken as soon as it frees and the retry window matches the harness budget instead of expiring early.

Instrumented sweep confirmed: **848 boots, 0 orphaned starts, max ENTER→serving 0.474 s, median 0.333 s, zero bind retries**. All diagnostics were then removed (verified: no `_diag`/`boot_diag` references, `/tmp` write audit clean, AST parses) and the final sweep run on the clean tree.

**Net diff: 0 test deletions, 0 `test_suite/` fixes, 0 `test_helpers/` fixes, 3 `implementation/` fixes (1 logic — `routes_admin.py::create_cancellation` rung-33-before-rung-14; 2 startup-only — `start.sh` find_spec probe, `app.py::_bind` retry cadence).**

### Orchestrator independent verification (per the clean-first-sweep protocol) — all clean
- All 8 `results.N.json` re-parsed independently: **105 individual rows each**, `passed=105 failed=0 total=105`, status set exactly `{'passed'}`, sorted test-name lists byte-identical to round 1 in all 8 rounds.
- `def test_` = 105 == `Design:` tags = 105 (47 Difficulty + 58 Corner).
- 0 occurrences of `pytest.mark.skip` / `xfail` / `skipif` / `pytest.skip` in `test_suite/` or `test_helpers/`.
- Impl grep for `sqlite|json.dump|pickle|/tmp|datetime.now|utcnow|time.time()` → empty (the one `store.py` docstring mention excluded).
- Independent route diff (scaffold `endpoints[]` vs in-process `app.url_map`, params normalized): **74 / 74, MISSING 0, EXTRA 0**.
- Each `round.N.log` contains `Killed` exactly once (the expected pre-boot server swap for test #1) and `Traceback` zero times.
- `find test_suite test_helpers implementation -newer results.1.json` → empty (nothing edited after the final sweep).

## Step 7b: Friction cross-check audit (read-only, orchestrator-initiated) — 2026-08-08T18:25:00.000Z

Run because 7 un-adjudicated friction points plus a near-clean sweep means Step 7's green exit proves less than it looks: a test that asserts on a friction passes only by agreeing with *this* impl's adjudication, so a different faithful implementer would fail it. That is latent unfairness a green sweep cannot detect, and it must be established by a positive check.

**Overall judgement: the 105-test green result is FAIR.** No test's setup, request, or assertion discriminates between the two PRD-faithful readings of any of the seven frictions. Four are genuinely untouched (frictions 2, 5, 7, and the forward-shipment limb of 1); the four that *are* touched (1-cheque, 3, 4, 6) were re-derived from first principles and yield byte-identical expected outcomes under both readings. A different implementer choosing the opposite reading on any friction — or on all seven — would still pass 105/105. **0 DEPENDS verdicts.**

Per-friction verdicts (all generator claims independently re-derived, not restated):
1. **Gate C** — forward-shipment limb CLEAN (all 11 creation sites are on boxes whose only member is `RELEASABLE`); cheque limb AGREEMENT-BY-CONSTRUCTION at `test_09:47` — the cheque is 600,000 cents against the strictly-greater 500,000 cap, so Reading A gives `ERR_FORM_1583_INCOMPLETE` (409) and Reading B gives `ERR_DEPOSIT_CAP_EXCEEDED` (422); the test asserts only `status_code >= 400` plus `validate_error_is_one_of([...])`, which the audit confirmed does **not** cross-check HTTP status. Both write nothing.
2. **Rung 7 error id** — CLEAN. Complete inventory of the suite's five synthetic-UUID uses: two path ids (rung 3), one `plan_tier_id` (rung 5), one `carrier_rule_id` (rung 6), one scan path id (rung 3). No unresolvable body `mail_item_id` / `mail_item_ids` member anywhere.
3. **OCR multiplier** — AGREEMENT-BY-CONSTRUCTION, load-bearing claim verified: **exactly one `OCR` scan request exists in the whole suite** (`test_06:286`), and it dies at rung 21 `ERR_SCAN_CONSENT_REQUIRED` before a job row exists. Every ledger assertion re-derived at `INTERIOR` (multiplier 1): straddling request ⌈40/25⌉ = 2 jobs → `10 × 25 × 1 = 250`; loyalty close 4 × 25 pages × 25 = 2500 → subtotal 40500 ≥ 40000 → 10 % → discount 4050, total 36450. Every figure identical under both readings.
4. **Superseding disposition** — AGREEMENT-BY-CONSTRUCTION for the refusal (both second-lodge tests are `SHRED`-over-`SHRED`, equal rank: Reading A fails rung 27's *strictly-lower* test, Reading B fails rung 14 — both 409, both write nothing, and the assertion list is exactly `{ERR_DISPOSITION_CONFLICT, ERR_INVALID_STATE}`); CLEAN for the supersession (no test asserts `SUPERSEDED`/`LOST_PRECEDENCE`; `precedence_rank` asserted only at three first-lodge-from-`HELD` sites).
5. **Multiple RA add-ons** — CLEAN. Four attachments across four distinct mailboxes; deactivate only ever invoked with a single add-on present.
6. **RECIPIENT tranche** — AGREEMENT-BY-CONSTRUCTION, two independent reasons re-derived: every RECIPIENT metering event is in cycle 1, and the max accepted members on any box is 2 against an allowance of 3. Both asserted ledger rows land `IN_TIER` / `unit_rate_cents 0` / `amount_cents 0` under both rules. Two indirect exposures (`outstanding_overage_cents == 0` at `test_01:153` and `:293`) also cleared.
7. **BillingCycle `version`** — CLEAN, verified independently: complete grep of every `version` read in `test_suite/` returns Box, MailItem and DepositBatch only. `assert_billing_cycle` delegates to `assert_common_fields`, whose only version constraints are `isinstance(int)` and `>= 1` — satisfied by 2 (Reading A) and 3 (Reading B) alike.

### Near-miss register — tests fair only by accident (10 entries; prior max 6)
The most useful artifact of the run: each is one small edit away from unfair.
1. `test_09:47` — the literal `600000`. Fairness on friction 1 rests **entirely** on it exceeding the cap. Changing it to `500000` splits refusal vs. HTTP 201 — maximal divergence, and the most fragile guarantee in the suite.
2. `test_08:169` — adding `accept_form=False` to one fixture call makes every referenced member `BLOCKED` → `ERR_FORM_1583_INCOMPLETE` vs `ERR_ITEM_NOT_CONSOLIDATABLE`, and line 187 asserts the exact id.
3. `test_07:139` — `"SHRED"` → `"DEPOSIT"` (rank 1 < 4) turns the equal-rank tie into the supersession branch: 201 + `SUPERSEDED` vs 409 `ERR_INVALID_STATE`.
4. `test_06:267` — two load-bearing values: `interior_scan_consent=False` stops the sole `OCR` request at rung 21, and the default `included_scan_pages = 50` would keep it in-tier anyway.
5. `test_08:108` — the excluded piece is excluded by a *missing FORWARD disposition*, not a blocked member, so the referenced set is homogeneous. A mixed set would split Reading A's own two sub-variants ("every referenced member" vs "any one").
6. `test_10:150` — a second `attach_registered_agent(box, "NV", 1)` would make the 1-day deadline govern under Reading B and the shred succeed.
7. `test_12:200` — adding `assert closed["version"] == 2` is literally one line from unfair.
8. `test_04:105` / `test_01:156` — the suite's only body-FK-not-found tests happen to target non-mail-item resources; one test passing `UNKNOWN_UUID` as `mail_item_id` would expose friction 2.
9. `test_02:124` — structurally the closest approach to the tranche divergence (4 members on a cap-3 box) but none files a Form 1583, so nothing is metered.
10. `test_09:187` — cheques resolving to nobody exercise the "no matched member" corner, but the sole member is `RELEASABLE` so no reading fires.

### Two robustness caveats carried forward
1. Fairness on friction 1 rests on a single integer (`test_09:64`). The module docstring explains the intent but does not say the number is load-bearing.
2. **Friction 1 is really three-way for forward shipments**, not two-way — §2.8 names "every referenced member", "any one of them", or "not at all", and the impl picked the middle (`routes_disposition.py:170-186`). The suite never builds a mixed referenced set, so all three agree everywhere; fair, but zero coverage of that interaction.

## Step 8: Finalize PRD — 2026-08-08T18:27:00.000Z

`PRD_FINALIZED.md` written.

### Line counts
- `PRD.md`: 589 lines — `PRD_FINALIZED.md`: 589 lines — **0.0 % line delta** (3 lines revised in place, no lines added or removed; +1,207 characters).

### Changes
- **§2.9 ladder preamble (line 190)** — revise — the "strictly ascending numeric order" universal now carries "with a single declared exception stated at rung 33 and applying to one endpoint only", so it is no longer a false universal — `routes_admin.py:293-296`.
- **§2.9 rung 33 (line 224)** — revise — appended the carve-out: on `POST /boxes/{id}/cancellation` (the only endpoint rung 33 applies to) rung 33 runs ahead of rung 14; earlier rungs including rung 12's lifecycle gate still precede it; rung 14 still fires there for any non-`ACTIVE` `service_status` with no outstanding request; no other rung is reordered anywhere — `routes_admin.py:293-296`.
- **§3.13 lodging paragraph (line 451)** — revise — pinned which of the paragraph's two stated preconditions is evaluated first and which error each produces — `routes_admin.py:293-296`.

FIX 2 (`start.sh` `find_spec` probe) and FIX 3 (`app.py` `_bind` retry cadence) got **no PRD edit**: both are startup-only, with no HTTP-observable surface, and the PRD says nothing about process boot.

### Per-edit pre-edit search log (NO-NEW-MISMATCH rule)

**Edit 1 — §2.9 preamble.** (a) Subject: the global claim that all 36 rungs evaluate in ascending order. (b) Enumerated every `# rung 14` site — `routes_mail.py:117,158,191,281,327`, `routes_disposition.py:35,101,238`, `routes_checks.py:71,140`, `routes_admin.py:82,116,170,253,295,330,353`, `routes_roster.py:198`; every rung-33 site — `routes_admin.py:293` only; every `ERR_CANCELLATION_ALREADY_PENDING` raise — `routes_admin.py:294` only. Confirmed exactly one endpoint deviates. (c) Wrote "a single declared exception … applying to one endpoint only" rather than a bare "except as noted below", so the preamble cannot be read as licensing ad-hoc reordering at the other 17 rung-14 sites.

**Edit 2 — §2.9 rung 33.** (a) Subject: the rung-33-before-rung-14 carve-out. (b) Enumerated `routes_admin.py:279-300` (`create_cancellation` — rung 9, rung 12 `gate_b`, then rung 33, then rung 14); `routes_admin.py:162-210` (`resolve_review` ESCALATED_CLOSURE branch also consults `store.live_cancellation` but raises `ERR_INVALID_STATE`); `routes_admin.py:314-342` (`withdraw` sets `service_status = ACTIVE` alongside `WITHDRAWN`, confirming the reachability argument); `routes_admin.py:345-353` (`finalize`); `routes_disposition.py:109` (other `live_cancellation` caller — SOP retention, unrelated); `store.py:150-153` (`live_cancellation` = `REQUESTED`/`FINAL_FORWARD`); `ladder.py:246-274` (`cancellation_create` is *not* on `GATE_A_OPERATIONS`, and `gate_b` runs before rung 33). (c) Three adjustments: scoped the sentence to "the only endpoint this rung applies to" so it says nothing about `resolve_review`'s parallel check; added "Every earlier rung, rung 12's lifecycle gate included, still runs before this one" because a bare "rung 33 runs first" would have wrongly hoisted it above rungs 8/9/12; added the rung-14-still-fires clause and "no other rung is reordered on this or any other endpoint" to fence the other 17 sites.

**Edit 3 — §3.13.** (a) Subject: ordering of the two lodging preconditions and which error each yields. (b) Enumerated `routes_admin.py:281-300`; `routes_admin.py:261-276` (`_create_cancellation`, shared by lodging and escalated closure); `routes_admin.py:206-209` and §3.11 (escalated-closure creation path, left untouched); `routes_admin.py:338-341` (withdraw). (c) First draft said "even though lodging has by then already moved its `service_status` to `CLOSING`"; softened to "even though its `service_status` is by then no longer `ACTIVE`", because a live request can also originate from an escalated-closure resolution, where it was the resolution and not lodging that set `CLOSING` — the original wording would have been a false universal about how the box left `ACTIVE`.

## Step 9: Complete PRD — 2026-08-08T18:45:00.000Z

`PRD_COMPLETED.md` is written. Structure verified intact (headings identical, all 151 table rows preserved, zero remaining un-adjudicated points).

**Files:** `PRD_FINALIZED.md` 589 lines / 119,878 chars → `PRD_COMPLETED.md` 596 lines / 146,183 chars (**+7 lines, +26,305 chars**). 52 paragraphs touched; no new sections, no headings added, no table altered.

**Counts:** 52 changes — **7 friction-point adjudications**, **31 ambiguity pins**, **14 mismatch revisions**.

### The 7 pre-adjudicated frictions (all verified present and now pinned)
- §2.8 — friction 1 — Gate C over check-logging (over the payee-matched member; skipped when none resolves) and over forward-shipment creation (fails only when NO referenced member is `RELEASABLE`) — `routes_checks.py:74-81`, `routes_disposition.py:177-186`
- §2.9 — friction 2 — rung 7 returns the resource-typed id `ERR_MAIL_ITEM_NOT_FOUND` for body `mail_item_id`/`mail_item_ids` — `routes_disposition.py:155-159`, `routes_checks.py:58-61`
- §3.6 — friction 3 — OCR multiplier lives only on `ScanJob.charge_cents`; ledger `unit_rate_cents` is the bare plan rate — `routes_mail.py:300-306`
- §3.7 — friction 4 — superseding disposition admitted onto a piece already `PENDING_DISPOSITION`; equal rank is `ERR_DISPOSITION_CONFLICT` — `routes_disposition.py:35-46`
- §3.10 — friction 5 — several active add-ons allowed; governing = most recently created active; deactivate targets it — `store.py:122-128`, `routes_admin.py:40-44`
- §3.12 — friction 6 — `RECIPIENT` tranche keyed on the cycle's `recipients_consumed` — `domain.py:97-114`
- §3.12 — friction 7 — cycle `version` advances by exactly 1 across a close — `domain.py:271-291`, `response.py:45-63`

### Question A — "does any endpoint CONSULT this field?" (11 findings, largest source)
`holder_email`/`holder_name` recorded but notification never reads or dispatches (§3.1) · `home_address_line`/`rejection_reason`/`accepted_by_user_id` never read back, a member may hold many forms (§3.3) · `doc_type` required and validated but consulted by nothing, not even a filter (§3.3) · `package_acceptance_fee_cents` never enters a ledger entry, cycle total or prepaid debit (§3.5) · `charge_cents` reported on the job only, never billed (§3.6) · the three forward price fields and `total_weight_lb` never billed, `destination_address` never read (§3.8) · `business_date` echoed only, cutoff keyed on the clock hour (§3.9) · `jurisdiction_code` validated then never read, `retention_days` is the whole statute (§3.10) · review `reason` varies no downstream behaviour (§3.11) · `forwarding_address` never read, no forward is ever created by the closure timeline (§3.13) · `abandonment_date` triggers nothing, no return-to-sender sweep exists — it is only arithmetic input to `destruction_eligible_on` (§3.13).

### Question B — universal quantifiers (7 findings)
`Recipient` scope on the one non-piece endpoint compares the member's own id (§2.1) · rung 8 has three exceptions: both catalogue listings and the cheque listing (§2.9 r8) · `status` is enum-checked against the *collection's* member set, unknown query params ignored (§2.9 r10) · rung 36 reaches exactly 3 endpoints and storage accrual meters `OVERAGE` even when `allows_overage` is false (§2.9 r36/§3.12) · no endpoint templates two ids, so the belonging rule has no site (§2.10) · the `PLAN_CHANGE` entry is the one declared exception to quota-tranche-partition (§2.11) · `RELEASABLE → BLOCKED` also re-derives dependents, PRD claimed only the other direction (§3.3).

### Question C — derived status vs gate check (1 finding, high value)
§2.8 — Gate C is **narrower** than `release_eligibility`: clauses 4/5 own no rung, so a member `BLOCKED` on `GUARANTOR_BLOCKED`/`ROSTER_NOT_AUTHORIZED` **passes** Gate C — `ladder.py:286-309`.

### Question D — unenforced uniqueness/scope (3 findings)
A cheque's `mail_item_id` is checked for existence only, not scoped to the batch's mailbox/state/disposition (§3.9) · duplicate ids collapsed, `item_count`/`excluded_item_count` are over distinct ids so repeats do not earn the discount (§3.8) · `box_number` is the mailbox collection's only uniqueness (§3.1).

### Question E — projections and ordering (4 findings)
Non-integer `limit`/`offset` are 400, over-range `offset` is an empty page, non-enum filters compared as literal strings, `active` must be `true`/`false` (§2.3) · ids minted monotonically, making the `id` tie-break a true extension of creation order (§2.4) · the Box resource projects `release_gate_state`, `roster_authorized_count`, `outstanding_overage_cents` (§3.1) · the cheque listing scopes a `BoxHolder` by filter, not by 403 (§3.9).

### Question F — precedence, unreachable legs, one-bump semantics (12 findings)
Unknown route → `ERR_BOX_NOT_FOUND` 404, bad method → `ERR_VALIDATION` 405, trailing slash insignificant, non-object body 400 (§2.2) · a no-crossing re-derivation rewrites `blocked_reason` without bumping `version`/`updated_at` (§3.3) · the `VERIFIED PHOTO` precondition is checked *after* rung 15 so the notary sees 403 first (§3.3) · roster move and `RECIPIENT` metering fire only from `PENDING` (§3.3) · PATCH is optional-field, empty-body-legal, declared from every status including `REMOVED`, re-derives nothing (§3.2) · rung 6 pre-empts the pairing rule, which runs on the raw `item_class` before rung 10 (§3.4) · acceptance has no custody-state precondition — a `REFUSED` package is acceptable (§3.5) · an unmatched piece with `signature_required` fails rung 22 (§3.5) · scan requests have no rung-14 precondition at all; guards evaluate 17-19 → 20 → 21, not in prose order (§3.6) · the winner clause at execute is unreachable, at most one `PENDING` request ever exists (§3.7) · cancel leaves prices and `excluded_item_count` intact against `item_count` 0 (§3.8) · `NOT_ENDORSED` holds leave `matched_recipient_id` null / `match_mode` `NONE`, and such a cheque can never be rematched (§3.9).

### Question G — remaining pins beyond the 7 (5 findings)
An already-`ACCRUING` piece keeps accruing in `PENDING_DISPOSITION`; the axis is evaluated at exactly four moments (§3.12) · the escalated-closure live-cancellation guard returns `ERR_INVALID_STATE`, evaluated before rung 15 (§3.11) · withdraw/finalize rung-4 target selection, withdraw also requires `service_status` `CLOSING` (§3.13) · rung 34 precedes rung 35 (PRD prose named them in the opposite order) and rung 34 sees only SOP pieces still in custody (§3.13) · finalization's cycle close skips the `period_end` precondition (§3.13).

**Ladder carve-out verified:** §2.9 rung 33 and §3.13 both describe rung 33 ahead of rung 14 on `POST /boxes/{id}/cancellation` only, with rung 12 still running first — matching `routes_admin.py:284-296` exactly. No other rung is reordered anywhere; left unchanged.

### Orchestrator final verification — all clean
- `diff` of all `^#` headers, `PRD.md` vs `PRD_COMPLETED.md` → **empty** (Step 9 added no sections).
- Line/char ledger: PRD 589/118,776 → FINALIZED 589/119,878 → COMPLETED 596/146,183.
- `find test_suite test_helpers implementation -newer results.1.json` → **empty again after Step 9** (the completeness pass touched no code).
- All 8 `results.N.json` re-read: `105/105`, `failed=0`, unchanged.

---

# PIPELINE COMPLETE — 105/105 on all 8 rounds, 0 deletions, 1 logic fix.
