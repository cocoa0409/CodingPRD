from routes import (
    clock as _clock,
    funders as _funders,
    providers as _providers,
    programs as _programs,
    clients as _clients,
    intakes as _intakes,
    consent_grants as _consent,
    referrals as _referrals,
    transport_plans as _tp,
    outcome_reports as _or,
)


def register_all(app):
    _clock.register(app)
    _funders.register(app)
    _providers.register(app)
    _programs.register(app)
    _clients.register(app)
    _intakes.register(app)
    _consent.register(app)
    _referrals.register(app)
    _tp.register(app)
    _or.register(app)
