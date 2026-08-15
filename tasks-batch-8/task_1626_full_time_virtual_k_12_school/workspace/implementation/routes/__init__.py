from flask import Blueprint


def make_blueprint(name):
    return Blueprint(name, __name__, url_prefix="/vks")
