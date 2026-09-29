"""Lightweight typed aliases and containers for the test suite.

These carry no behaviour: they exist so that scenario builders can hand a named
bundle of already-created records to a test instead of a bare tuple.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

Json = Dict[str, Any]
Headers = Dict[str, str]


@dataclass
class ParticipantBundle:
    """A participant plus the records created alongside it during bootstrap."""

    participant: Json
    account: Optional[Json] = None
    policies: List[Json] = field(default_factory=list)
    customer_accounts: List[Json] = field(default_factory=list)

    @property
    def id(self) -> str:
        return self.participant["id"]

    @property
    def routing_number(self) -> str:
        return self.participant["routing_number"]

    @property
    def version(self) -> int:
        return self.participant["version"]

    @property
    def account_id(self) -> str:
        assert self.account is not None, "bundle has no prefunded position account"
        return self.account["id"]

    @property
    def policy(self) -> Json:
        assert self.policies, "bundle has no segment policy"
        return self.policies[-1]

    @property
    def customer_account(self) -> Json:
        assert self.customer_accounts, "bundle has no customer account"
        return self.customer_accounts[0]

    @property
    def customer_account_id(self) -> str:
        return self.customer_account["id"]


@dataclass
class RailScenario:
    """A whole rail: one or more participants plus the day's settlement cycle."""

    alpha: ParticipantBundle
    beta: Optional[ParticipantBundle] = None
    cycle: Optional[Json] = None
    extra: Dict[str, Json] = field(default_factory=dict)

    @property
    def cycle_id(self) -> str:
        assert self.cycle is not None, "scenario has no settlement cycle"
        return self.cycle["id"]
